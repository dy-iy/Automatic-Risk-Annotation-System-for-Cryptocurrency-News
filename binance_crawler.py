import requests
import datetime
import csv
from pathlib import Path
s = requests.Session()
url = "https://www.binance.com/bapi/composite/v4/friendly/pgc/feed/news/list"
s.headers.update(
    {
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.binance.com/zh-CN/square/news/all",
        "Origin": "https://www.binance.com",
        "clienttype": "web",
        #"bnc-location": "CN",
        #"bnc-time-zone": "Asia/Shanghai",
        "lang": "zh-CN",
    }
)
s.get("https://www.binance.com/zh-CN/square/news/all")
#s.cookies.set("lang", "zh-CN", domain=".binance.com", path="/")
#s.cookies.set("BNC-Location", "CN", domain=".binance.com", path="/")
params = {
    "pageIndex": 1,
    "pageSize": 20,
    "strategy": 6,
    "tagId": 0,
    "featured": "false",
}
r = s.get(url, params=params)
print("链接状态",r.status_code)

#data=r.json()
#inner_data=data["data"]["vos"]
#print(type(inner_data))
#print(inner_data[0].keys())

save_dir = Path(".\craw_news")
save_dir.mkdir(exist_ok=True)
now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
csv_path = save_dir / f"binance_news_{now}.csv"
with open(csv_path, "w", encoding="utf-8-sig",newline="") as f:
    writer=csv.writer(f)
    writer.writerow(["新闻id","内容","链接"])
    news_index=1
    max_page=100
    for page in range(1,max_page+1):
        params["pageIndex"]=page
        material = s.get(url, params=params)
        js=material.json()
        data=js["data"]["vos"]
        for item in data:
            news_date=datetime.datetime.fromtimestamp(item.get("date"))
            news_link=item.get("webLink")
            news_title=item.get("title")
            news_text=item.get("subTitle")
            if news_index%50==0 :
                print(f"已爬取:{news_index}条新闻\n")
            # print(f"编号:{news_index}\n"
            #       f"标题:{news_title}\n"
            #       f"时间:{news_date}\n"
            #       f"内容:{news_text}\n"
            #       f"链接:{news_link}\n"
            #       f"{'='*100}")
            writer.writerow(
                [
                    news_index,
                    news_title+news_text,
                    news_link,
                ]
            )
            news_index+=1;