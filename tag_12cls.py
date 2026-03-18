import re
import math
import pandas as pd

CSV_PATH = r"news.csv"
OUT_PATH = r"risk_12cls.csv"

df = pd.read_csv(CSV_PATH)
df["内容"] = df["内容"].fillna("").astype(str)

# ---------------- 基础抽取 ----------------
PCT_RE = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*%')
AMT_RE = re.compile(
    r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*'
    r'(亿美元|千万美元|百万美元|万美元|美元|USDT|USDC)',
    re.IGNORECASE
)

TIME_HINTS = ["分钟","小时","日内","短时间","瞬间","盘中","24小时","24h","今晨","今日","当天"]

# ---------------- 全局排除 / 缓和语义 ----------------
NEG_FRAUD = ["反欺诈","防欺诈","反诈骗宣传","欺诈检测","反洗钱","AML","合规体系","风控系统"]
NEG_REG_ONLY_TALK = ["呼吁", "建议", "提议", "敦促", "讨论", "区分", "澄清", "拟", "草案", "征求意见"]
NEG_TICKER_COLLISION = ["BTC原油", "原油出口", "杰伊汉港", "阿塞拜疆"]

# 否定/缓和/修复语义：用于多个规则共享
NEG_NO_RISK = [
    "不涉及安全事件", "未涉及安全事件", "无安全事件",
    "不涉及资产异常", "未涉及资产异常",
    "不涉及资产安全", "未涉及资产安全",
    "不影响用户资产", "用户资金未受影响", "未造成资金损失",
    "无资金损失", "未造成损失", "已修复", "完成修复",
    "已恢复", "恢复正常", "误报", "并非攻击", "并非被盗",
    "不存在被盗风险", "并不存在被盗风险", "并非漏洞",
    "并非安全事故", "非安全事故"
]

NEG_PLANNED_MAINT = [
    "例行维护", "计划内维护", "系统升级", "例行升级",
    "例行系统升级", "按计划推进", "常规维护"
]

NEG_INTERNAL_TRANSFER = [
    "内部调拨", "内部转移", "冷钱包内部调拨", "钱包归集",
    "资金归集", "地址归集", "热钱包迁移", "冷钱包迁移",
    "官方钱包迁移"
]

USD_UNIT_MULT = {
    "美元": 1.0,
    "USDT": 1.0,
    "USDC": 1.0,
    "万美元": 1e4,
    "百万美元": 1e6,
    "千万美元": 1e7,
    "亿美元": 1e8,
}

def has_any(text, kws):
    t = (text or "")
    return any(k in t for k in kws)

def extract_max_pct(text):
    mx = 0.0
    for m in PCT_RE.finditer(text or ""):
        try:
            mx = max(mx, abs(float(m.group(1))))
        except:
            pass
    return mx

def extract_usd_equiv(text):
    usd = 0.0
    for m in AMT_RE.finditer(text or ""):
        raw, unit = m.group(1), m.group(2)
        raw = raw.replace(",", "")
        try:
            val = float(raw)
        except:
            continue
        u = unit.upper()
        usd += val * USD_UNIT_MULT.get(u, 0.0)
    return usd

def clip01(x: float) -> float:
    return 0.0 if x < 0 else (1.0 if x > 1 else float(x))

def smooth_strength(x, x0, scale):
    if x <= x0:
        return 0.0
    return 1.0 - math.exp(-(x - x0) / scale)

# ---------------- 风险打分 ----------------

# 1) 合约/链上漏洞攻击（高风险，直接 0.9+）
KW_HACK = ["漏洞", "攻击", "被盗", "盗取", "重入", "闪电贷", "利用漏洞", "黑客", "exploit", "hacker", "入侵"]
def score_hack(text):
    if has_any(text, NEG_NO_RISK):
        # 明确“已修复/未受影响/并非攻击”时大幅降权
        if has_any(text, KW_HACK):
            return 0.20
    if has_any(text, KW_HACK):
        usd = extract_usd_equiv(text)
        return clip01(0.90 + 0.08 * smooth_strength(usd, 50_000, 200_000))
    return 0.0

# 2) 诈骗/跑路/rug（高风险，但排除“反欺诈/AML”语境）
KW_FRAUD = ["诈骗","骗局","庞氏","传销","跑路","rug","rugpull","钓鱼","假冒","冒充","卷款"]
def score_fraud(text):
    if has_any(text, NEG_FRAUD):
        return 0.0
    if has_any(text, KW_FRAUD):
        return 0.88
    return 0.0

# 3) 监管/法律风险：必须“监管机构词” + “执法动作词”
REG_ACTORS = ["SEC","CFTC","司法部","检察","法院","监管","执法","警察","法官","审计","调查机构","税务"]
REG_ACTIONS = ["起诉","指控","调查","罚款","制裁","传唤","逮捕","拘留","认罪","和解","判决","冻结","查封","禁令","诉讼"]
def score_regulatory(text):
    if has_any(text, ["SEC"]) and has_any(text, NEG_REG_ONLY_TALK) and not has_any(text, REG_ACTIONS):
        return 0.0
    if has_any(text, REG_ACTORS) and has_any(text, REG_ACTIONS):
        return 0.80
    return 0.0

# 4) 交易所/链/钱包运维风险：暂停充提/宕机/维护（中高）
KW_OUTAGE = ["暂停提现","暂停充提","暂停充值","提现暂停","充值暂停","维护","钱包维护","宕机","系统故障","无法交易","停止充提","网络拥堵"]
def score_outage(text):
    if not has_any(text, KW_OUTAGE):
        return 0.0

    # 计划内维护、已恢复、明确无资产风险 -> 降低
    if has_any(text, NEG_PLANNED_MAINT) or has_any(text, NEG_NO_RISK):
        if "暂停提现" in text or "停止充提" in text or "暂停充提" in text:
            return 0.35
        return 0.20

    # 真正异常暂停充提更高
    if has_any(text, ["暂停提现","暂停充提","停止充提","提现暂停","充值暂停"]):
        return 0.72

    # 网络拥堵/维护/宕机相对略低
    if has_any(text, ["宕机","系统故障","无法交易"]):
        return 0.68

    return 0.55

# 5) 稳定币异常：稳定币 + 脱锚/跌破1美元/peg/depeg/异常价格
STABLES = ["USDT","USDC","DAI","FDUSD","TUSD","UST","USDD","FRAX","PYUSD","稳定币"]
STABLE_HINTS = ["脱锚","锚定","锚离","peg","depeg","跌破1美元","跌破 1 美元","回到1美元"]
STABLE_NUM = re.compile(r'\b0\.9\d\b|\b1\.0\d\b')
def score_stablecoin(text):
    if not has_any(text, STABLES):
        return 0.0
    if has_any(text, STABLE_HINTS) or STABLE_NUM.search(text or ""):
        return 0.85
    return 0.0

# 6) 清算/爆仓：金额越大越高
KW_LIQ = ["爆仓","强平","清算","liquidation","永续","合约","杠杆","保证金"]
def score_liquidation(text):
    if not has_any(text, KW_LIQ):
        return 0.0
    usd = extract_usd_equiv(text)
    if usd <= 0:
        return 0.55
    return clip01(0.55 + 0.30 * smooth_strength(usd, 500_000, 2_000_000))

# 7) 大额转账/巨鲸
KW_WHALE = ["巨鲸","whale","转入","转出","转入交易所","转出交易所","从匿名地址","从未知地址","链上","地址"]
def score_whale(text):
    if not has_any(text, KW_WHALE):
        return 0.0

    # 内部调拨、归集、冷钱包迁移等，明显降低
    if has_any(text, NEG_INTERNAL_TRANSFER) or has_any(text, NEG_NO_RISK):
        usd = extract_usd_equiv(text)
        if usd > 0:
            return 0.15
        return 0.05

    usd = extract_usd_equiv(text)
    if usd <= 0:
        return 0.25
    return clip01(0.35 + 0.40 * smooth_strength(usd, 200_000, 1_500_000))

# 8) 行情异常波动：>=8% 才给风险；强波动词可直接触发
KW_SHOCK = ["闪崩","插针","瀑布","腰斩","暴跌","暴涨","剧烈波动","瞬间暴跌","瞬间拉升"]
def score_volatility(text):
    pct = extract_max_pct(text)
    has_time = has_any(text, TIME_HINTS)

    # 如果明确说明“并非漏洞/并非安全事故”，则作为市场风险，不给太高
    has_softener = has_any(text, NEG_NO_RISK)

    if has_any(text, KW_SHOCK):
        base = 0.50 if has_softener else 0.60
        if has_time:
            base += 0.05
        return clip01(base + 0.25 * smooth_strength(pct, 10, 20))

    if pct < 8:
        return 0.0

    base = 0.30 + (0.05 if has_time else 0.0)
    # 纯行情波动整体上限别太高
    return clip01(base + 0.40 * smooth_strength(pct, 8, 20))

# 9) 项目治理 / 团队异常风险（新增）
KW_TEAM = [
    "创始人失联","团队失联","删除社交媒体账号","删除账号","官网无法访问",
    "官网无法打开","停止运营","停更","项目方失联","团队突然解散",
    "官方失联","核心成员离职","多签异常"
]
def score_team(text):
    if has_any(text, KW_TEAM):
        return 0.82
    return 0.0

# 10) 偿付能力 / 储备 / 流动性风险（新增）
KW_SOLV = [
    "偿付能力","兑付","挤兑","储备不足","储备透明度不足","流动性危机",
    "流动性不足","资不抵债","现金流压力","负债","财务困境","无法兑付"
]
def score_solvency(text):
    if has_any(text, KW_SOLV):
        # 如果还提到了稳定币或发行方，风险更高
        if has_any(text, STABLES) or has_any(text, ["发行方","储备资产"]):
            return 0.88
        return 0.78
    return 0.0

# 11) 基础设施 / 协议层异常风险（新增）
KW_INFRA = [
    "跨链桥异常","跨链桥故障","预言机异常","预言机失灵","停止出块",
    "分叉异常","共识失败","RPC故障","节点故障","主网故障","网络停止"
]
def score_infra(text):
    if has_any(text, KW_INFRA):
        if has_any(text, NEG_NO_RISK):
            return 0.25
        return 0.75
    return 0.0

# 12) 宏观 / 政策冲击风险（新增）
KW_MACRO = [
    "美元走强","美元指数走强","油价飙升","美债收益率走高","加息预期",
    "风险偏好下降","避险情绪升温","宏观利空","政策收紧","禁令"
]
def score_macro(text):
    if has_any(text, KW_MACRO):
        pct = extract_max_pct(text)
        base = 0.35
        return clip01(base + 0.20 * smooth_strength(pct, 3, 10))
    return 0.0

# ---------------- 总分：取 max ----------------
SCORERS = [
    score_hack,
    score_fraud,
    score_regulatory,
    score_outage,
    score_stablecoin,
    score_liquidation,
    score_whale,
    score_volatility,
    score_team,
    score_solvency,
    score_infra,
    score_macro,
]

def risk_score(text: str) -> float:
    if has_any(text, NEG_TICKER_COLLISION):
        return 0.0
    scores = [fn(text) for fn in SCORERS]
    return float(max(scores)) if scores else 0.0

df["risk"] = df["内容"].apply(risk_score)

out_df = df[["序号","内容","链接","risk"]]
out_df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
print("Saved:", OUT_PATH)
print(out_df["risk"].describe())
