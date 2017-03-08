# coding:utf-8

import os
import _thread as thread
from time import sleep
from socket import inet_aton
from . import logging, data_dir, launcher_dir, LRUCache, isip, isipv4
from local.GlobalConfig import GC

if '4' in GC.LINK_PROFILE:
    from .dns import dns_resolve
else:
    from .dns import dns_resolve1, dns_resolve2, dns_resolve3

    def dns_resolve(host):
        iplist = dns_resolve1(host)
        if not iplist:
            iplist = dns_resolve2(host)
            if not iplist:
                iplist = dns_resolve3(host)
        return iplist

class DirectIPv4Database:
    #载入 IPv4 保留地址和 CN 地址数据库，数据来源：
    #    https://ftp.apnic.net/apnic/stats/apnic/delegated-apnic-latest
    #    https://github.com/17mon/china_ip_list/raw/master/china_ip_list.txt
    #    +---------+
    #    | 4 bytes |                     <- data length
    #    +---------------+
    #    | 224 * 4 bytes |               <- first ip number index
    #    +---------------+
    #    |  2n * 4 bytes |               <- cn ip ranges data
    #    +------------------------+
    #    | b'end' and update info |      <- end verify
    #    +------------------------+
    def __init__(self, filename):
        from struct import unpack
        with open(filename, 'rb') as f:
            #读取 IP 范围数据长度 BE Ulong -> int
            data_len, = unpack('>L', f.read(4))
            #读取索引数据
            index = f.read(224 * 4)
            #读取 IP 范围数据
            data = f.read(data_len)
            #简单验证结束
            if f.read(3) != b'end':
                raise ValueError('%s 文件格式损坏！' % filename)
            #读取更新信息
            self.update = f.read(64).decode('utf-8')
        #格式化并缓存索引数据
        #使用 struct.unpack 一次性分割数据效率更高
        #每 4 字节为一个索引范围 fip：BE short -> int，对应 IP 范围序数
        self.index = unpack('>' + 'h' * (224 * 2), index)
        #每 8 字节对应一段直连 IP 范围和一段非直连 IP 范围
        self.data = unpack('4s' * (data_len // 4), data)

    def __contains__(self, ip):
        #转换 IP 为 BE Uint32，实际类型 bytes
        nip = inet_aton(ip)
        #确定索引范围
        index = self.index
        fip = nip[0]
        #从 224 开始都属于保留地址
        if fip >= 224:
            return True
        fip *= 2
        lo = index[fip]
        if lo < 0:
            return False
        #结束位置加 1
        #避免无法搜索从当前索引结尾地址到下个索引开始地址
        hi = index[fip + 1] + 1
        #与 IP 范围比较确定 IP 位置
        data = self.data
        while lo < hi:
            mid = (lo + hi) // 2
            if data[mid] > nip:
                hi = mid
            else:
                lo = mid + 1
        #根据位置序数奇偶确定是否属于直连 IP
        return lo & 1

directipdb = os.path.join(data_dir, 'directip.db')
direct_cache = LRUCache(GC.DNS_CACHE_ENTRIES//2)
ipdbmtime = 0

def isdirect(host):
    if ipdb is None:
        return False
    hostisip = isip(host)
    if hostisip:
        ips = host,
    elif host in direct_cache:
        return direct_cache[host]
    else:
        ips = dns_resolve(host)
    ipv4 = None
    for ip in ips:
        if isipv4(ip):
            ipv4 = ip
            break
    if ipv4:
        direct = ipv4 in ipdb
    else:
        direct = False
    if not hostisip:
        direct_cache[host] = direct
    return direct

ipdbmtime = os.path.getmtime(directipdb)

def load_ipdb():
    global ipdb, IPDBVer
    ipdb = DirectIPv4Database(directipdb)
    IPDBVer = ipdb.update

def check_modify():
    global ipdbmtime
    while True:
        sleep(10)
        if os.path.exists(directipdb):
            filemtime = os.path.getmtime(directipdb)
        else:
            filemtime = 0
        if filemtime > ipdbmtime:
            try:
                load_ipdb()
                ipdbmtime = filemtime
                direct_cache.clear()
                logging.warning('检测到直连 IP 数据库更新，已重新加载：%s。', IPDBVer)
            except Exception as e:
                logging.warning('检测到直连 IP 数据库更新，重新加载时出现错误，'
                                '请重新下载：\n%r', e)

if os.path.exists(directipdb):
    load_ipdb()
else:
    ipdb = None
    IPDBVer = '数据库文件未安装'
    buildscript = os.path.join(launcher_dir, 'buildipdb.py')
    logging.warning('无法在找到直连 IP 数据库，Win 用户可用托盘工具下载更新，'
                    '其它系统请运行脚本 %r 下载更新。', buildscript)

thread.start_new_thread(check_modify, ())
