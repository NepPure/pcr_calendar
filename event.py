import os
import json
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import aiohttp
import asyncio
import math
import functools
import re
import demjson

# type 0普通 1双倍 2 公会战 3 活动

event_data = {
    'cn': [],
    'tw': [],
    'jp': [],
}

event_updated = {
    'cn': '',
    'tw': '',
    'jp': '',
}

lock = {
    'cn': asyncio.Lock(),
    'tw': asyncio.Lock(),
    'jp': asyncio.Lock(),
}

list_api = 'https://static.biligame.com/pcr/gw/calendar.js?t=%s'


def cache(ttl=timedelta(hours=1), arg_key=None):
    def wrap(func):
        cache_data = {}

        @functools.wraps(func)
        async def wrapped(*args, **kw):
            nonlocal cache_data
            default_data = {"time": None, "value": None}
            ins_key = 'default'
            if arg_key:
                ins_key = arg_key + str(kw.get(arg_key, ''))
                data = cache_data.get(ins_key, default_data)
            else:
                data = cache_data.get(ins_key, default_data)

            now = datetime.now()
            if not data['time'] or now - data['time'] > ttl:
                try:
                    data['value'] = await func(*args, **kw)
                    data['time'] = now
                    cache_data[ins_key] = data
                except Exception as e:
                    raise e

            return data['value']

        return wrapped

    return wrap


@cache(ttl=timedelta(hours=3), arg_key='url')
async def query_data(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()
    except:
        pass
    return None


@cache(ttl=timedelta(hours=3), arg_key='url')
async def query_cn_data(url):
    try:
        url = url % datetime.now()
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                text_data = await resp.text()
                searchObj = re.search(
                    r'\s*var\s+data\s*\=\s*(\[[\w\W]*?\])', text_data, re.MULTILINE | re.I)
                group_result = searchObj.groups()
                if len(group_result) > 0:
                    return demjson.decode(group_result[0])
    except:
        pass
    return None


def get_cn_hdtype(hdtype, hdtitle=None):
    if hdtype == 'tdz':
        return 3
    elif hdtype == 'qdhd':
        if hdtitle and '扭蛋' in hdtitle:
            return 1
        return 2
    elif hdtype == 'jqhd':
        return 1
    else:
        return 0


async def load_event_cn():
    result = await query_cn_data(url=list_api)
    if result:
        event_data['cn'] = []
        filter_time = datetime.now()-timedelta(days=60)
        tmp_event = {}
        hdcontent_rex = re.compile(
            r"<div class='cl-t'>(.+?)<\/div>(?:<div class='cl-d'>(.+?)<\/div>)?")
        for month_data in result:
            ctime = datetime.strptime(
                f"{month_data['year']}-{month_data['month']}-1", r"%Y-%m-%d")
            if ctime < filter_time:
                # 两个月前的还解析个啥
                continue

            for hdday, hddic in month_data['day'].items():
                hdstarttime = datetime.strptime(
                    f"{month_data['year']}-{month_data['month']}-{hdday} 05:00", r"%Y-%m-%d %H:%M")

                for hdtype, hdcontent in hddic.items():
                    if not hdcontent:
                        # 无此类型活动
                        continue
                    if hdtype == 'qdhd':
                        # 双倍和抽卡一般04:59
                        hdendtime = datetime.strptime(
                            f"{month_data['year']}-{month_data['month']}-{hdday} 04:59", r"%Y-%m-%d %H:%M")
                    else:
                        hdendtime = datetime.strptime(
                            f"{month_data['year']}-{month_data['month']}-{hdday} 23:59", r"%Y-%m-%d %H:%M")

                    hdcontent_list = hdcontent_rex.findall(
                        hdcontent)
                    for hdc in hdcontent_list:
                        if len(hdc) < 1:
                            continue
                        hdtitle = hdc[0]
                        if len(hdc) > 1:
                            hdtitle += ' '+hdc[1]
                        if hdtitle in tmp_event.keys():
                            # 更新时间，反正要遍历不是
                            if hdstarttime < tmp_event[hdtitle]['start']:
                                tmp_event[hdtitle]['start'] = hdstarttime
                            if hdendtime > tmp_event[hdtitle]['end']:
                                tmp_event[hdtitle]['end'] = hdendtime

                        else:
                            tmp_event[hdtitle] = {'title': hdtitle,
                                                  'start': hdstarttime,
                                                  'end': hdendtime,
                                                  'type': get_cn_hdtype(hdtype, hdtitle)}

        for key, event in tmp_event.items():
            # 处理只有一天的特殊情况
            if event['end'] < event['start']:
                event['end'] += timedelta(hours=19)

            event_data['cn'].append(event)
        return 0
    return 1


async def load_event_tw():
    data = await query_data(url='https://pcredivewiki.tw/static/data/event.json')
    if data:
        event_data['tw'] = []
        for item in data:
            start_time = datetime.strptime(
                item['start_time'], r"%Y/%m/%d %H:%M")
            end_time = datetime.strptime(
                item['end_time'], r"%Y/%m/%d %H:%M")
            event = {'title': item['campaign_name'],
                     'start': start_time, 'end': end_time, 'type': 1}
            if '倍' in event['title']:
                event['type'] = 2
            elif '戰隊' in event['title']:
                event['type'] = 3
            event_data['tw'].append(event)
        return 0
    return 1


async def load_event_jp():
    data = await query_data(url='https://cdn.jsdelivr.net/gh/pcrbot/calendar-updater-action@gh-pages/jp.json')
    if data:
        event_data['jp'] = []
        for item in data:
            start_time = datetime.strptime(
                item['start_time'], r'%Y/%m/%d %H:%M:%S')
            end_time = datetime.strptime(
                item['end_time'], r'%Y/%m/%d %H:%M:%S')
            event = {'title': item['name'],
                     'start': start_time, 'end': end_time, 'type': 1}
            if '倍' in event['title']:
                event['type'] = 2
            elif '公会战' in event['title']:
                event['type'] = 3
            event_data['jp'].append(event)
        return 0
    return 1


async def load_event(server):
    if server == 'cn':
        return await load_event_cn()
    elif server == 'tw':
        return await load_event_tw()
    elif server == 'jp':
        return await load_event_jp()
    return 1


def get_pcr_now(offset):
    pcr_now = datetime.now()
    if pcr_now.hour < 5:
        pcr_now -= timedelta(days=1)
    pcr_now = pcr_now.replace(
        hour=5, minute=0, second=0, microsecond=0)  # 用早5点做基准
    pcr_now = pcr_now + timedelta(days=offset)
    return pcr_now


async def get_events(server, offset, days):
    events = []
    pcr_now = get_pcr_now(0)

    await lock[server].acquire()
    try:
        t = pcr_now.strftime('%y%m%d')
        if event_updated[server] != t:
            if await load_event(server) == 0:
                event_updated[server] = t
    finally:
        lock[server].release()

    start = pcr_now + timedelta(days=offset)
    end = start + timedelta(days=days)
    end -= timedelta(hours=5)  # 晚上12点结束

    for event in event_data[server]:
        if end > event['start'] and start < event['end']:  # 在指定时间段内 已开始 且 未结束
            event['start_days'] = math.ceil(
                (event['start'] - start) / timedelta(days=1))  # 还有几天开始
            event['left_days'] = math.floor(
                (event['end'] - start) / timedelta(days=1))  # 还有几天结束
            events.append(event)
    # 按type从大到小 按剩余天数从小到大
    events.sort(key=lambda item: item["type"]
                * 100 - item['left_days'] - item['start_days'], reverse=True)
    return events


if __name__ == '__main__':
    async def main():
        await load_event_cn()
        events = await get_events('jp', 0, 1)
        for event in events:
            print(event)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
