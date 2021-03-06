# 房天下spider
# author: #27

# 目标：
# 爬取待售新房信息
# 1、爬取新房列表数据
# 包含：位置（区域）、状态、电话、户型图
# 2、每条新房对应该新房的动态列表
# 包含：预售、开盘、交房、包含价格信息的动态

# todo: 使用框架

import gzip
import timeit
import re
import threading
from exception_output import ExceptionOutput
from sqlite_wrapper import SqliteWrapper
from urllib import request
from urllib import error
from io import BytesIO
from bs4 import BeautifulSoup

# 房天下新房按区进行爬取
regions = ['pudong', 'baoshan', 'minhang', 'putuo', 'xuhui', 'yangpu', \
            'hongkou', 'huangpu', 'jingan', 'luwan', 'changning']
BASE_URL = 'http://newhouse.sh.fang.com'

spidered_list = []
news_id = 0

exception = ExceptionOutput()

db_ftx_xf = SqliteWrapper('ftx_xf.db')
db_ftx_xf.drop_table('xf_info')
db_ftx_xf.drop_table('news')
db_ftx_xf.create_table('create table xf_info(name TEXT PRIMARY KEY NOT NULL, status TEXT, price TEXT, location TEXT, phone TEXT, size TEXT, '
                       'area TEXT, decoration TEXT, park_num TEXT, house_num TEXT, service_fee TEXT, service_company TEXT, tree TEXT)')
db_ftx_xf.create_table('create table news(id INT PRIMARY KEY NOT NULL, news_time TEXT, type INT, house_name TEXT, title TEXT, content TEXT)')


def do_spider_house_list(url):
    """
    执行list spider
    """
    if url in spidered_list:
        return []
    spidered_list.append(url)
    html_bs4 = get_html_bs4(url)
    if not html_bs4:
        return
    # 获取每个item实体
    list_items = html_bs4.find(id='newhouse_loupai_list').find_all('div', 'nlc_details')
    # 从每个item实体提取 名称、状态、价格、位置、电话
    threads = []
    for item in list_items:
        t = threading.Thread(target=spider_house_list, args=(item,))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 分页递归
    pages_root = html_bs4.find('div', 'page')
    if pages_root:
        next_page = pages_root.find('li', 'fr').find('a', 'next')
        if next_page:
            return do_spider_house_list(BASE_URL + next_page['href'])
        else:
            return
    return


def spider_house_list(item):
    """
    新房list信息提取
    """
    print('%s is running' % threading.current_thread().name)
    house_dict = {}
    house_dict['name'] = item.find('div', 'nlcd_name').a.string.strip()
    house_dict['status'] = item.find('div', 'fangyuan').span.string
    item_price = item.find('div', 'nhouse_price')
    house_dict['price'] = item_price.text.strip() if item_price else None
    house_dict['location'] = item.find('div', 'address').a['title']
    item_phone = item.find('div', 'tel')
    house_dict['phone'] = item_phone.p.text if item_phone else None 
    # 获取每个item的detail信息
    item_link = item.find('div', 'nlcd_name').a['href']
    spider_house_detail(item_link, house_dict)
    db_ftx_xf.insert('xf_info', house_dict)
    print(house_dict)


def spider_house_detail(url, house_dict):
    """
    获取新房详情信息：房型、动态
    """
    html_bs4 = get_html_bs4(url)
    if not html_bs4:
        return
    size_zone = html_bs4.find('div', 'zlhx')
    size_origin = size_zone.text.strip() if size_zone else None
    size = ''
    if not size_origin or size_origin == '暂无':
        size = size_origin
    else:
        sizes = size_origin.split('\n\n')
        for s in sizes:
            m = re.match(r'(\w+)\([^\d]*(\d+).*\)', s)
            g = m.groups()
            size += g[0] + ':' + g[1] + ' '
    house_dict['size'] = size
    info_link = html_bs4.find('a', text='楼盘详情')['href']
    detail_info = spider_detail_info(info_link)
    for key in ['area', 'decoration', 'park_num', 'house_num', 'service_fee', 'service_company', 'tree']:
        house_dict[key] = detail_info[key]
    news_link = html_bs4.find('a', title=re.compile(r'动态$'))['href']
    if 'http' not in news_link:
        news_link = 'http://newhouse.sh.fang.com/' + news_link
    spider_detail_news(news_link, house_dict['name'])


def spider_detail_info(url):
    """
    获取新房的一些详细信息：环线位置 装修情况 停车位 总户数 物业费 物业公司 绿化率
    """
    target_list = [('area', '环线位置'), ('decoration', '装修状况'), ('park_num', '停车位'), ('house_num', '总户数'), ('service_fee', '物业费描述'),
                   ('service_company', '物业公司'), ('tree', '绿化率')]
    detail_info = {}
    html_bs4 = get_html_bs4(url)
    labels = html_bs4.find_all('div', 'list-left')
    for l in labels:
        for key, text in target_list:
            pattern_text = r'^' + text
            pattern = re.compile(pattern_text)
            if pattern.match(l.text.strip().replace(' ', '')):
                node_content = l.parent.find('div', class_=re.compile(r'^list-right'))
                detail_info[key] = node_content.text.strip().replace('\n', '').replace('\t', '')
    return detail_info


def spider_detail_news(url, name):
    """
    获取新房动态：动态、预售证、开盘
    """
    html_bs4 = get_html_bs4(url)
    if not html_bs4:
        return
    for info in ['blog', 'sale', 'open']:
        news_items_root = html_bs4.find(id='gushi_' + info)
        if not news_items_root:
            continue
        news_items = news_items_root.find('ul', 'zs-list').find_all('li')
        for item in news_items:
            tmp_dict = {}
            global news_id
            tmp_dict['id'] = news_id
            news_id += 1
            tmp_dict['news_time'] = item.find('div', 'sLTime').text.strip()
            tmp_dict['house_name'] = name
            tmp_dict['type'] = info
            if info == 'blog':
                tmp_dict['title'] = item.h2.a.string
                tmp_dict['content'] = item.p.text.strip()
            elif info == 'sale':
                tmp_dict['content'] = item.find_all('p')[0].string
            else:
                pinfo = item.find_all('p')
                tmp_dict['content'] = pinfo[len(pinfo) - 1].string
            db_ftx_xf.insert('news', tmp_dict)


def get_html_bs4(url):
    """
    获取每个链接的BeautifulSoup格式化网页内容
    """
    try:
        response = request.urlopen(url)
        if response.headers.get('Content-Encoding') == 'gzip':  # gzip压缩时先解压
            compressedData = response.read()
            compressedStream = BytesIO(compressedData)
            gzipper = gzip.GzipFile(fileobj=compressedStream)
            html = gzipper.read()
        else:
            html = response.read()
        html = BeautifulSoup(html, 'html.parser', from_encoding='gb2312')
    except (error.HTTPError, error.URLError) as e:
        print('读取url数据出现错误：', e)
        exception.spider_exception(url, e)
        return
    except error as e:
        exception.spider_exception(url, e)
        return
    return html


def clear_exception_log():
    """
    清空异常日志
    """
    exception.exception_log_clear('spider_exception.txt')
    exception.exception_log_clear('sqlite_exception.txt')


def spider_run():
    """
    程序运行入口
    """
    clear_exception_log()
    for region in regions:
        base_url = BASE_URL + '/house/s/' + region + '/a77-b82/'
        do_spider_house_list(base_url)


if __name__ == '__main__':
    print(timeit.timeit('spider_run()', setup='from __main__ import spider_run'))
