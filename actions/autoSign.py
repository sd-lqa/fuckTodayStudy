import base64
import json
import os
import random
import re
import uuid

from pyDes import des, CBC, PAD_PKCS5
from requests_toolbelt import MultipartEncoder

from login.Utils import Utils
from todayLoginService import TodayLoginService
from liteTools import DT


class AutoSign:
    # 初始化签到类
    def __init__(self, todayLoginService: TodayLoginService, userInfo, encryptApi):
        self.session = todayLoginService.session
        self.host = todayLoginService.host
        self.userInfo = userInfo
        self.taskInfo = None
        self.task = None
        self.form = {}
        self.fileName = None
        self.encryptApi = encryptApi

    # 获取未签到的任务
    def getUnSignTask(self):
        headers = self.session.headers
        headers['Content-Type'] = 'application/json'
        # 第一次请求接口获取cookies（MOD_AUTH_CAS）
        url = f'{self.host}wec-counselor-sign-apps/stu/sign/getStuSignInfosInOneDay'
        self.session.post(url, headers=headers,
                          data=json.dumps({}), verify=False)
        # 第二次请求接口，真正的拿到具体任务
        res = self.session.post(url, headers=headers,
                                data=json.dumps({}), verify=False)
        if res.status_code == 404:
            raise Exception('您没有任何签到任务，请检查自己的任务类型！')
        res = DT.resJsonEncode(res)
        if len(res['datas']['unSignedTasks']) < 1:
            raise Exception('当前暂时没有未签到的任务哦！')
        # 获取最后的一个任务
        latestTask = res['datas']['unSignedTasks'][0]
        self.taskInfo = {
            'signInstanceWid': latestTask['signInstanceWid'],
            'signWid': latestTask['signWid']
        }

    # 获取具体的签到任务详情
    def getDetailTask(self):
        url = f'{self.host}wec-counselor-sign-apps/stu/sign/detailSignInstance'
        headers = self.session.headers
        headers['Content-Type'] = 'application/json'
        res = self.session.post(url, headers=headers,
                                data=json.dumps(self.taskInfo), verify=False)
        res = DT.resJsonEncode(res)
        self.task = res['datas']

    # 上传图片到阿里云oss
    def uploadPicture(self, picSrc):
        url = f'{self.host}wec-counselor-sign-apps/stu/oss/getUploadPolicy'
        res = self.session.post(url=url, headers={'content-type': 'application/json'}, data=json.dumps({'fileType': 1}),
                                verify=False)
        datas = DT.resJsonEncode(res).get('datas')
        fileName = datas.get('fileName')
        policy = datas.get('policy')
        accessKeyId = datas.get('accessid')
        signature = datas.get('signature')
        policyHost = datas.get('host')
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:50.0) Gecko/20100101 Firefox/50.0'
        }
        multipart_encoder = MultipartEncoder(
            fields={  # 这里根据需要进行参数格式设置
                'key': fileName, 'policy': policy, 'OSSAccessKeyId': accessKeyId, 'success_action_status': '200',
                'signature': signature,
                'file': ('blob', open(picSrc, 'rb'), 'image/jpg')
            })
        headers['Content-Type'] = multipart_encoder.content_type
        self.session.post(url=policyHost,
                          headers=headers,
                          data=multipart_encoder)
        self.fileName = fileName

    # 获取图片上传位置
    def getPictureUrl(self):
        url = f'{self.host}wec-counselor-sign-apps/stu/sign/previewAttachment'
        params = {'ossKey': self.fileName}
        res = self.session.post(url=url, headers={'content-type': 'application/json'}, data=json.dumps(params),
                                verify=False)
        photoUrl = DT.resJsonEncode(res).get('datas')
        return photoUrl

    # 填充表单
    def fillForm(self):
        # 判断签到是否需要照片
        if self.task['isPhoto'] == 1:
            # 如果是需要传图片的话，那么是将图片的地址（相对/绝对都行）存放于此photo中
            picBase = self.userInfo['photo']
            # 如果直接是图片
            if os.path.isfile(picBase):
                picSrc = picBase
            else:
                picDir = os.listdir(picBase)
                # 如果该文件夹里没有文件
                if len(picDir) == 0:
                    raise Exception("您的图片上传已选择一个文件夹，且文件夹中没有文件！")
                # 拼接随机图片的图片路径
                picSrc = os.path.join(picBase, random.choice(picDir))
            self.uploadPicture(picSrc)
            self.form['signPhotoUrl'] = self.getPictureUrl()
        else:
            self.form['signPhotoUrl'] = ''
        self.form['isNeedExtra'] = self.task['isNeedExtra']
        if self.task['isNeedExtra'] == 1:
            extraFields = self.task['extraField']
            userItems = self.userInfo['forms']
            extraFieldItemValues = []
            for i in range(len(extraFields)):
                if i >= len(userItems):
                    raise Exception("您的config表单中form字段不够，请检查")
                userItem = userItems[i]['form']
                extraField = extraFields[i]
                if self.userInfo['checkTitle'] == 1:
                    if userItem['title'].strip() != extraField['title'].strip():
                        raise Exception(
                            f'\r\n第{i + 1}个配置出错了\r\n您的标题为：{userItem["title"]}\r\n系统的标题为：{extraField["title"]}')
                extraFieldItems = extraField['extraFieldItems']
                flag = False
                data = []
                # 遍历所有的选项
                for extraFieldItem in extraFieldItems:
                    # 如果当前选项为历史选项，将临时保存一下以便config未找到对应值时输出
                    if extraFieldItem['isSelected']:
                        data.append(extraFieldItem['content'])
                    # 初始化局部变量 并初始化数据字典的key
                    extraFieldItemValue = {}
                    extraFieldItemValue.setdefault('extraFieldItemValue', None)
                    extraFieldItemValue.setdefault('extraFieldItemWid', None)
                    # 如果表单的选项值和配置的值相等
                    if extraFieldItem['content'] == userItem['value']:
                        extraFieldItemValue['extraFieldItemWid'] = extraFieldItem['wid']
                        # 如果是其它字段（other字段）
                        if extraFieldItem['isOtherItems'] == 1:
                            if 'other' in userItem:
                                flag = True
                                extraFieldItemValue['extraFieldItemValue'] = userItem['other']
                            else:
                                raise Exception(
                                    f'\r\n第{i + 1}个配置项的选项不正确，该字段存在“other”字段，请在配置文件“title，value”下添加一行“other”字段并且填上对应的值'
                                )
                        # 如果不是其它字段
                        else:
                            flag = True
                            extraFieldItemValue['extraFieldItemValue'] = userItem['value']
                        extraFieldItemValues.append(extraFieldItemValue)
                if not flag:
                    raise Exception(
                        f'\r\n第{ i + 1 }个配置出错了\r\n表单未找到你设置的值：{userItem["value"]}\r\n，你上次系统选的值为：{ ",".join(data) }')
            self.form['extraFieldItems'] = extraFieldItemValues
        self.form['signInstanceWid'] = self.task['signInstanceWid']
        self.form['longitude'] = self.userInfo['lon']
        self.form['latitude'] = self.userInfo['lat']
        self.form['isMalposition'] = self.task['isMalposition']
        self.form['abnormalReason'] = self.userInfo['abnormalReason']
        self.form['position'] = self.userInfo['address']
        self.form['uaIsCpadaily'] = True
        self.form['signVersion'] = '1.0.0'

    # DES加密
    def DESEncrypt(self, s, key='b3L26XNL'):
        key = key
        iv = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        k = des(key, CBC, iv, pad=None, padmode=PAD_PKCS5)
        encrypt_str = k.encrypt(s)
        return base64.b64encode(encrypt_str).decode()

    # 提交签到信息
    def submitForm(self):
        deviceId = str(uuid.uuid1())
        model = "RuoLi Phone Plus Pro Max 2021"
        appVersion = "9.0.12"
        extension = {
            "lon": self.userInfo['lon'],
            "model": model,
            "appVersion": appVersion,
            "systemVersion": "11",
            "userId": self.userInfo['username'],
            "systemName": "android",
            "lat": self.userInfo['lat'],
            "deviceId": deviceId
        }
        headers = {
            'User-Agent': self.session.headers['User-Agent'],
            'CpdailyStandAlone': '0',
            'extension': '1',
            'Cpdaily-Extension': self.DESEncrypt(json.dumps(extension)),
            'Content-Type': 'application/json; charset=utf-8',
            'Accept-Encoding': 'gzip',
            'Host': re.findall('//(.*?)/', self.host)[0],
            'Connection': 'Keep-Alive'
        }

        forSubmit = {
            "appVersion": appVersion,
            "deviceId": deviceId,
            "lat": self.userInfo['lat'],
            "lon": self.userInfo['lon'],
            "model": model,
            "systemName": "android",
            "systemVersion": "11",
            "userId": self.userInfo['username'],
        }
        forBody = json.dumps(self.form, ensure_ascii=False)
        print(f'{Utils.getAsiaTime()} 正在请求加密数据...')
        res = self.session.post(self.encryptApi, params=forSubmit, data=forBody.encode("utf-8"), verify=False)
        if res.status_code != 200:
            raise Exception("加密表单数据出错，请反馈")
        res = res.json()
        if res['status'] != 200:
            raise Exception(res['message'])
        forSubmit['version'] = 'first_v2'
        forSubmit['calVersion'] = 'firstv'
        forSubmit['bodyString'] = res['data']['bodyString']
        forSubmit['sign'] = res['data']['sign']

        res = self.session.post(f'{self.host}wec-counselor-sign-apps/stu/sign/submitSign', headers=headers,
                                data=json.dumps(forSubmit), verify=False)
        res = DT.resJsonEncode(res)
        return res['message']
