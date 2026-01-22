# 文件名: henu_core.py
import requests
import re
import math
import random
import base64
import json
import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


class HenuLibraryBot:
    # 区域映射表 (可按需补充)
    LOCATIONS = {
        "金明三楼南走廊": "15",
        "金明三楼北走廊": "16",
        "金明三楼走廊": "17",
        "金明四楼走廊": "22",
        "金明四楼书库": "23",
        "金明五楼走廊": "26",
        "金明七层南自习": "30",
        "金明七层北自习": "31",
        "明伦二层借书": "67",
        "明伦三层现刊": "41",
        "明伦三层报纸": "40",
        "明伦三层借书": "39",
        "明伦四层第三": "47",
        "明伦四层第二": "44",
        "明伦四层第一": "43"

    }

    AES_CHARS = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"

    def __init__(self, username, password, saved_cookies: dict = None):
        """
        :param username: 学号
        :param password: 密码
        :param saved_cookies: 从数据库加载的 cookies 字典 (可选)
        """
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest"
        })
        self.base_url = "https://zwyy.henu.edu.cn"
        self.cas_login_url = "https://ids.henu.edu.cn/authserver/login"

        # 如果传入了 cookie (TGT)，则加载
        if saved_cookies:
            self.session.cookies.update(saved_cookies)

    def get_cookies(self):
        """返回当前 session 的 cookies 字典，用于存入数据库"""
        return self.session.cookies.get_dict()

    # ================== 加密辅助 ==================
    def _random_string(self, length):
        ret = ""
        for _ in range(length):
            ret += self.AES_CHARS[math.floor(random.random() * len(self.AES_CHARS))]
        return ret

    def _encrypt_password(self, password, salt):
        random_prefix = self._random_string(64)
        iv_str = self._random_string(16)
        text = random_prefix + password
        key_bytes = salt.encode('utf-8')
        iv_bytes = iv_str.encode('utf-8')
        try:
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            padded_data = pad(text.encode('utf-8'), AES.block_size)
            return base64.b64encode(cipher.encrypt(padded_data)).decode('utf-8')
        except:
            return password

    def login(self):
        """
        尝试登录。优先使用 TGT 免密，失败则使用账号密码。
        返回: True (成功) / False (失败)
        """
        # 定义回调地址 (CAS 登录成功后必须跳回这里，否则无法获取 Token)
        service_url = f"{self.base_url}/cas/index.php?callback={self.base_url}/home/web/f_second"
        # 带有 service 参数的登录页地址
        cas_auth_url = f"{self.cas_login_url}?service={service_url}"

        print(f"[*] Starting login for {self.username}...")

        # 1. 尝试 TGT 免密登录
        try:
            resp = self.session.get(cas_auth_url, allow_redirects=True)
            if "zwyy.henu.edu.cn" in resp.url and "authserver" not in resp.url:
                print(f"[√] TGT Valid. Logged in automatically.")
                self._ensure_access_token()
                return True
        except Exception as e:
            print(f"[!] TGT check failed: {e}")

        # 2. 如果 TGT 失效，且提供了密码，则进行密码登录
        if not self.password:
            print("[X] No password provided.")
            return False

        try:
            # 【重要修正】这里必须访问带 service 参数的 URL，否则登录后不会跳转
            resp = self.session.get(cas_auth_url)

            # 解析参数
            try:
                execution = re.search(r'name="execution" value="(.*?)"', resp.text).group(1)
                salt = re.search(r'id="pwdEncryptSalt" value="(.*?)"', resp.text).group(1)
            except AttributeError:
                print("[!] Failed to parse execution/salt. Page content might have changed.")
                return False

            encrypted_pw = self._encrypt_password(self.password, salt)

            data = {
                'username': self.username,
                'password': encrypted_pw,
                'captcha': '',
                '_eventId': 'submit',
                'cllt': 'userNameLogin',
                'dllt': 'generalLogin',
                'lt': '',
                'execution': execution
            }

            # 提交登录 (向当前 URL 提交，包含 service 参数)
            print("[*] Submitting login form...")
            login_resp = self.session.post(resp.url, data=data)

            # 验证结果
            if "zwyy.henu.edu.cn" in login_resp.url:
                print("[√] Login success! Redirected to library.")
                self._ensure_access_token()
                return True
            else:
                # 调试信息：如果失败，打印出停留在了哪个页面
                print(f"[X] Login failed. Landed on: {login_resp.url}")
                # 检查是否因为验证码
                if "验证码" in login_resp.text:
                    print("[!] Failed reason: CAPTCHA required.")
                elif "密码错误" in login_resp.text:
                    print("[!] Failed reason: Incorrect Password.")
                return False

        except Exception as e:
            print(f"[!] Login Exception: {e}")
            return False

    def _ensure_access_token(self):
        """确保 cookies 中有 access_token，没有则访问一次主页激活"""
        if 'access_token' not in self.session.cookies:
            self.session.get(f"{self.base_url}/home/web/f_second")

    # ================== 预约辅助逻辑 ==================
    def get_space_id_by_no(self, area_id, seat_no, day):
        """使用 spaces_old 接口查找座位 ID"""
        url = f"{self.base_url}/api.php/spaces_old"
        params = {"area": area_id, "day": day, "startTime": "08:00", "endTime": "22:00"}
        headers = {
            "Referer": f"{self.base_url}/home/web/seat3?area={area_id}&day={day}&startTime=08%3A00&endTime=22%3A00"}

        try:
            res = self.session.get(url, headers=headers, params=params).json()
            if res.get('status') == 1 and 'list' in res.get('data', {}):
                target = str(seat_no).strip()
                for s in res['data']['list']:
                    s_name = str(s.get('name', '')).strip()
                    s_no = str(s.get('no', '')).strip()
                    if target == s_name or target == s_no:
                        return s['id']
        except Exception:
            pass
        return None

    def get_segment_id(self, area_id, day):
        """获取时间段 ID"""
        url = f"{self.base_url}/api.php/v3areadays/{area_id}"
        day_short = day.replace("-0", "-")
        headers = {"Referer": f"{self.base_url}/home/web/seat2/area/{area_id}/day/{day_short}"}

        try:
            res = self.session.get(url, headers=headers).json()
            if res.get('status') == 1:
                for item in res['data']['list']:
                    if item.get('day') == day:
                        return item.get('id')
        except Exception:
            pass
        return None

    # ================== 核心预约方法 ==================
    def reserve(self, location_name, seat_no, target_date):
        """
        执行预约
        :return: 字典 {'success': bool, 'msg': str}
        """
        # 1. 区域检查
        if location_name not in self.LOCATIONS:
            return {"success": False, "msg": f"区域 '{location_name}' 未定义"}

        area_id = self.LOCATIONS[location_name]

        # 2. 登录状态检查
        if 'access_token' not in self.session.cookies:
            return {"success": False, "msg": "未登录或 Access Token 丢失"}

        # 3. 获取 Segment ID
        segment = self.get_segment_id(area_id, target_date)
        if not segment:
            return {"success": False, "msg": f"未找到日期 {target_date} 的开放时间段"}

        # 4. 获取 Space ID
        space_id = self.get_space_id_by_no(area_id, seat_no, target_date)
        if not space_id:
            return {"success": False, "msg": f"在该区域未找到座位号: {seat_no}"}

        # 5. 提交预约
        book_url = f"{self.base_url}/api.php/spaces/{space_id}/book"
        # 先把 cookies 转为字典，自动解决冲突
        cookies_dict = self.session.cookies.get_dict()

        payload = {
            "userid": cookies_dict.get("userid"),
            "access_token": cookies_dict.get("access_token"),
            "segment": segment,
            "day": target_date,
            "startTime": "08:00",
            "endTime": "22:00",
            "type": 1,
            "operateChannel": 2
        }

        # Referer 是必须的
        day_short = target_date.replace("-0", "-")
        self.session.headers.update({
            "Referer": f"{self.base_url}/home/web/seat3?area={area_id}&segment={segment}&day={day_short}"
        })

        try:
            res = self.session.post(book_url, data=payload).json()
            is_success = (res.get('status') == 1)
            msg = res.get('msg', '未知返回结果')
            return {"success": is_success, "msg": msg}
        except Exception as e:
            return {"success": False, "msg": f"请求异常: {str(e)}"}