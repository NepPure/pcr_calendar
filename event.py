import os
import json
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import aiohttp
import asyncio
import math
import functools
import re

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

list_api = 'https://api.biligame.com/news/list.action?gameExtensionId=267&positionId=2&pageNum=1&pageSize=30&typeId='
detail_api = 'https://api.biligame.com/news/%s.action'


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


@cache(ttl=timedelta(hours=12), arg_key='url')
async def query_data(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                return await resp.json()
    except:
        pass
    return None


async def load_event_cn():
    result = await query_data(url=list_api)
    if result and 'code' in result and result['code'] == 0:
        event_data['cn'] = []
        datalist = result['data']
        for item in datalist:
            # ignore = False
            # for ann_id in ignored_ann_ids:
            #     if ann_id == item["id"]:
            #         ignore = True
            #         break
            # if ignore:
            #     continue

            # for keyword in ignored_key_words:
            #     if keyword in item['title']:
            #         ignore = True
            #         break
            #     if ignore:
            #         continue

            # 从正文中获取活动时间
            content_result = await query_data(url=detail_api % item["id"])
            if not (content_result and 'code' in content_result and content_result['code'] == 0):
                # 直接跳过？
                continue

            detail = content_result['data']['content']
            # 有些是直接写在卡池上的艹
            searchObj = re.search(
                r'(\d+)\/(\d+)\s+(?:维护后)?(\d+)?:?(\d+)?\s*(?:~|-)\s*(\d+)\/(\d+)\s+(\d+):(\d+)', detail, re.M | re.I)

            try:
                datelist = searchObj.groups()  # ('2021', '9', '17', '9', '17')
            except Exception as e:
                continue
            if not (datelist and len(datelist) >= 8):
                continue

            syear = datetime.now().year
            smonth = int(datelist[0])
            sday = int(datelist[1])
            shour = datelist[2] and int(datelist[2]) or 0
            sminute = datelist[3] and int(datelist[3]) or 0

            emonth = int(datelist[4])
            eday = int(datelist[5])
            ehour = int(datelist[6])
            eminute = int(datelist[7])
            eyear = smonth > emonth and syear+1 or syear

            start_time = datetime.strptime(
                f'{syear}-{smonth}-{sday} {shour}:{sminute}', r"%Y-%m-%d  %H:%M")
            end_time = datetime.strptime(
                f'{eyear}-{emonth}-{eday} {ehour}:{eminute}', r"%Y-%m-%d  %H:%M")
            event = {'title': item['title'],
                     'start': start_time,
                     'end': end_time,
                     'forever': False,
                     'type': 0}

            if '团队战' in item['title']:
                event['type'] = 3
            elif '倍' in item['title']:
                event['type'] = 2
            elif '开启' in item['title']:
                event['type'] = 1
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
        hour=18, minute=0, second=0, microsecond=0)  # 用晚6点做基准
    pcr_now = pcr_now + timedelta(days=offset)
    return pcr_now


async def get_events(server, offset, days):
    events = []
    pcr_now = datetime.now()
    if pcr_now.hour < 5:
        pcr_now -= timedelta(days=1)
    pcr_now = pcr_now.replace(
        hour=18, minute=0, second=0, microsecond=0)  # 用晚6点做基准

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
    end -= timedelta(hours=18)  # 晚上12点结束

    for event in event_data[server]:
        if end > event['start'] and start < event['end']:  # 在指定时间段内 已开始 且 未结束
            event['start_days'] = math.ceil(
                (event['start'] - start) / timedelta(days=1))  # 还有几天开始
            event['left_days'] = math.floor(
                (event['end'] - start) / timedelta(days=1))  # 还有几天结束
            events.append(event)
    # 按type从大到小 按剩余天数从小到大
    events.sort(key=lambda item: item["type"]
                * 100 - item['left_days'], reverse=True)
    return events


if __name__ == '__main__':
    async def main():
        await load_event_cn()
        events = await get_events('jp', 0, 1)
        for event in events:
            print(event)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
