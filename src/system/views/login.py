import base64
import hashlib
import json
from datetime import datetime, timedelta
from captcha.views import CaptchaStore, captcha_image
from django.contrib import auth
from django.contrib.auth import login
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView

from django.conf import settings

from application import dispatch
from src.system.models import Users
from src.utils.json_response import ErrorResponse, DetailResponse
from src.utils.request_util import save_login_log
from src.utils.serializers import CustomModelSerializer
from src.utils.validator import CustomValidationError
from src.open.views.wehcat import wechat_instance
from django.http import HttpResponse
import subprocess


class QrLoginView(APIView):
    authentication_classes = []
    permission_classes = []

    class FakeRequest():
        def __init__(self, hashkey) -> None:
            self.method = 'POST'
            self.headers = {}
            self.GET = {}
            self.accepted_renderer = {}
            self.path = '/wechatmp/cgi-bin/qrcode/create'
            self.data = {"expire_seconds": 604800, "action_name": "QR_STR_SCENE",
                         "action_info": {"scene": {"scene_str": hashkey}}}

    def get(self, request):
        hashkey = CaptchaStore.generate_key()
        row = CaptchaStore.objects.filter(hashkey=hashkey).first()
        id = row.id
        _request = self.FakeRequest(hashkey)
        response = wechat_instance.mp_request(_request)
        print('response', response)
        if (not isinstance(response, dict)):
            response = json.loads(response)
            ticket = response['ticket']
            # print(ticket)
            return DetailResponse(data={
                'url': f'https://mp.weixin.qq.com/cgi-bin/showqrcode?ticket={ticket}',
                'scence_id': id
            })
        else:
            return DetailResponse(data=response['errmsg'], code=response['errcode'])


class CaptchaView(APIView):
    authentication_classes = []
    permission_classes = []

    @swagger_auto_schema(
        responses={"200": openapi.Response("????????????")},
        security=[],
        operation_id="captcha-get",
        operation_description="???????????????",
    )
    def get(self, request):
        data = {}
        # print(dispatch.get_system_config_values("base.captcha_state"))
        # if dispatch.get_system_config_values("base.captcha_state"):
        hashkey = CaptchaStore.generate_key()
        id = CaptchaStore.objects.filter(hashkey=hashkey).first().id
        imgage = captcha_image(request, hashkey)
        # ??????????????????base64
        image_base = base64.b64encode(imgage.content)
        data = {
            "key": id,
            "image_base": "data:image/png;base64," + image_base.decode("utf-8"),
        }
        return DetailResponse(data=data)


class LoginSerializer(TokenObtainPairSerializer):
    """
    ?????????????????????:
    ??????djangorestframework-simplejwt???????????????
    """

    captcha = serializers.CharField(
        max_length=6, required=False, allow_null=True, allow_blank=True
    )

    class Meta:
        model = Users
        fields = "__all__"
        read_only_fields = ["id"]

    default_error_messages = {"no_active_account": _("??????/????????????")}

    def validate(self, attrs):
        captcha = self.initial_data.get("captcha", None)
        if dispatch.get_system_config_values("base.captcha_state"):
            if captcha is None:
                raise CustomValidationError("?????????????????????")
            self.image_code = CaptchaStore.objects.filter(
                id=self.initial_data["captchaKey"]
            ).first()
            five_minute_ago = datetime.now() - timedelta(hours=0, minutes=5, seconds=0)
            if self.image_code and five_minute_ago > self.image_code.expiration:
                self.image_code and self.image_code.delete()
                raise CustomValidationError("???????????????")
            else:
                if self.image_code and (
                        self.image_code.response == captcha
                        or self.image_code.challenge == captcha
                ):
                    self.image_code and self.image_code.delete()
                else:
                    self.image_code and self.image_code.delete()
                    raise CustomValidationError("?????????????????????")
        data = super().validate(attrs)
        data["name"] = self.user.name
        data["userId"] = self.user.id
        data["avatar"] = self.user.avatar
        dept = getattr(self.user, 'dept', None)
        if dept:
            data['dept_info'] = {
                'dept_id': dept.id,
                'dept_name': dept.name,
                'dept_key': dept.key
            }
        role = getattr(self.user, 'role', None)
        if role:
            data['role_info'] = role.values('id', 'name', 'key')
        request = self.context.get("request")
        request.user = self.user
        # ??????????????????
        save_login_log(request=request)
        return {"code": 200, "msg": "????????????", "data": data}


class LoginView(TokenObtainPairView):
    """
    ????????????
    """

    serializer_class = LoginSerializer
    permission_classes = []


class LoginTokenSerializer(TokenObtainPairSerializer):
    """
    ?????????????????????:
    """

    class Meta:
        model = Users
        fields = "__all__"
        read_only_fields = ["id"]

    default_error_messages = {"no_active_account": _("??????/???????????????")}

    def validate(self, attrs):
        if not getattr(settings, "LOGIN_NO_CAPTCHA_AUTH", False):
            return {"code": 400, "msg": "?????????????????????!", "data": None}
        data = super().validate(attrs)
        data["name"] = self.user.name
        data["userId"] = self.user.id
        return {"code": 200, "msg": "????????????", "data": data}


class LoginTokenView(TokenObtainPairView):
    """
    ????????????token??????
    """

    serializer_class = LoginTokenSerializer
    permission_classes = []


class LogoutView(APIView):
    def post(self, request):
        return DetailResponse(msg="????????????")


class ApiLoginSerializer(CustomModelSerializer):
    """??????????????????-????????????"""

    username = serializers.CharField()
    password = serializers.CharField()

    class Meta:
        model = Users
        fields = ["username", "password"]


class ApiLogin(APIView):
    """???????????????????????????"""

    serializer_class = ApiLoginSerializer
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        user_obj = auth.authenticate(
            request,
            username=username,
            password=hashlib.md5(password.encode(
                encoding="UTF-8")).hexdigest(),
        )
        if user_obj:
            login(request, user_obj)
            return redirect("/")
        else:
            return ErrorResponse(msg="??????/????????????")
