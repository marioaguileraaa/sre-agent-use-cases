"""Standalone offline PythonFunctionTool. All data is explicitly SIMULATED."""

import csv
import html
import io
import json
import math
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

# BEGIN STANDALONE REPORT HELPERS
# Kept identical in both files: each deployed Python tool is self-contained.
OUTPUT_DIRECTORY = Path("arc-defender-reports")
TRANSPORT_BUDGET_BYTES = 3500
MAX_ARTIFACT_BYTES = 4_800_000
MAX_DECODED_NODES = 2_000_000
MAX_DECODED_STRING_UNITS = 64_000_000
LOGO_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAggAAABUCAMAAADQ8T/0AAADAFBMVEXZnJfq36rn59yYo5/Zm1/o2diPsqXhbldanoTOzlnS"
    "3tCv2tCis6+v28/eaimpUml0qJaw5tHo8t5Ol3q2b4xbpoxszarjrsmo2cqhzqhVVVXescbw36Q+oHqK1LZ8wakAPz+7D1yE"
    "rqBtjIMAqlU/f3//AADCZY33vrFgkX0/roKmyb4AAAAjmGscm2v6+/n0uxb9/v4wjGkA///5+/lJl3kXoW38/Pp/f38A/wBt"
    "qpOu18dVpYZqqZH5+tOSyLLsuStLmXsAf3/7/Pu61DZUpYZytJroxlNts5f1/Po4l3Pu249qp5BElXa35dO3y0+pGFbQ+OuH"
    "uaZXnIJ5uqKWxrSKuaf8/Pv7/fvG59rvwQ/W+vBqmYjp6rHz68NZsY5omYiLxK9yp5RRo4O5yWZVnIGS0rlpmom50UdupZLX"
    "5ZVNl3rF1nH14ZDqWiqXGU6lyrvtwS5sqJGm1sQAfwC2zTmJt6YnoXLs87mUJFNZnIOb18JxtJqMu6u32MxEjHB5xKjpymzb"
    "56fP8uuz1s18uKP45vLR247B0jev1slHjXPU2dZ4u6LL6uGa0bpZqIn36PHR7OWn1L6mx7x//384o3no6Ot///9VqlVVqqr0"
    "5rZFoX3X9e7pYixomYltmYrr0mvJ5dmuRGzDzDp4xqhHoH3G8N30+NbO6uWc2ML26urM59u35diHtaTVZzOyZoXYXS7XdUyj"
    "I1qUx7e04tCkxbuUuayLu6zR5HbniGhktJWl0b722+281nD16LiizLzL7OSmzsJYpoh2p5iLqqKr0siu49brtq7B1Uo6mXXv"
    "yK/v5M7ux8/duiyVw7OTybfUmbRXlX3H3depRHL52NT16betFWWd48j35ZuqPnD22qzJbEf22ars0reqWoT259Gy8dlPjHWU"
    "ybZctpJWso49qoGuuri75diStqU6jHAejmSnyb3ouUuCp5vjp4+CqpqHq56XOGLsWxzK49iqzsQAVVXG2dHM5qR0waPT26HZ"
    "9u6bMVfqeFxvsJnqlmmArZ18W7uzAAABAHRSTlPj3qDo8d5f/F78IBsW4v7wO2Rsld/caLSj2wPBULdq4AT/jKMDBAHitU2U"
    "qgD9/vb+B/kB0M/+sgIBdjGwjfhN/rACkf6UcvuLK9Tyreku/v4laa9sNlJQcSr/F8/39ZOtae3K+8lNkv7O9pX65/7+M/9V"
    "RwL+7Pr5/pVGUdEb6XH889foU9H1/tXSEYomOHW16jTvAtIRAgMDcczq/uxy+xzr/1W0KNQXOOrs5YT+7f77/u1DGa009+2u"
    "SbL4kEvQL1YvbIsZzv+zu86y/orYy1LX3tKy/jrU8PH617TskSacG2yuySfQGNv+1P6y7Wpa+f/MQwMt2obzavz9yfCUGw0k"
    "UAAAItFJREFUeNrtXQd43MaVXjX3OLETp1xyyfUKgB7sgtu5XFJck6vdpbhLUqRIyuwUSySG6r1YspplSZZL3Hvv3Y4T93OJ"
    "Hcc1vfeeS7lc6uXeFAAzmMGScnRfzgznk0gJwGIHM/+89782CGjKFtE0lEpavTsOVfi1W159oPPvj9kHFyNtpr3lW0B1EGEY"
    "5DpX77isomx7/IfDQxM3EdjMtGkIhBpN25+8YvWhiim0PcPrW9GMUJiOQMDT+nTn6tsqptYu2zOcjM8gYfoBAcT8Cbnet4Uq"
    "ptwOre58Gs0gYZoBoUZDxStWX1ZxRG1H51BhZiinFRAiGkr2vq3iSNtlm4bGZ9TDNAJCRGvIvQkcQPthN3DG6Mx4Tg8g/JXW"
    "MNB7VsWbajs6/3OGKEwTIES0ps7eUEXFn4CE4MyIvvWBgLSm4TnlcFBVVRYJt3b+dEYiTAMgIK3hx73lcbCkPBJ2dLfODOhb"
    "Hgig4H9cXh4smDt3wWRIaJmhCW9xIERrwG4swxNDoS9Un376R7rKU4jDpRveUkgIokjNSuo/iaApdvz/kgahSCRSU1MDP1Hw"
    "zwQEpB1zxZ6KckBYgIHw4XB5JGy6cnIjkj0jUl6HyLxEgvIQrfQeigbFqQtGarj/rQwGJ5tZqQdocvsXCb+UQIlI3ZwSxKKo"
    "xvP/sl1QnKY3qEGT9V55RcAhip1lFQMFQvVkQLgMmw5/wgr1GyRt0hPqS6LRsihAqOXJA7EDBw7ENj4YR9qUQuqobFeR7zRP"
    "5a4oPgHtuFeeakFT7M2RDGOw3IAGbIKQ6y07x6GKKQGh4tXuJyYTnii1fnR0NBNHimlFheLQ6GhMPocGm2Oe1hrnlloQj2Ix"
    "lnHONqfiN6Hyg7K/WFfK69AMA36kk5n2KcCgBzr/9UyT/xTAIwjdLI7vR5NJEXwKtafq0hbpj55PJJIp/HSq3jcV8fg1N8h3"
    "GUx+fXT9xqYy3wMf/fpoq79EQFrPFd8N2XNctbbqCIEQCp/tKIehst6EoNaeow9r1RckYKKtAyacMvcmTxSOF+qzutyy6SJy"
    "IfTuhPd0ttSMERX1SbhI7jUpCkgjn6gbRGVJAFpBO29azT5PiXpKMI95vh/W99N1qXF846g/DnAakO52B39HOtMiBfiDcOFA"
    "nvS79IjQhaBWYANgpZB65FGqRDqvJxRXBGhH9g1/2p3hXf1jXVVru7qqJCD4cIRQ28t3Bm6hZw7ldpYhOkiLD8NjkGE3c+PC"
    "YEa1m+rpSMC50s3Ouaj2yz5ujNx5M3QzeTUbqY56/grnNla9KkQOunRDEg+nfSd2e93I1sXL5dk8RnBKOp9Ujvb+HH04T09h"
    "dkjaRtBXSGKA8Z2hUK4rePGGevKsC6Z1rraSm+YVA3RMdDOfQWpxAB9l39GMfIBwe+9sZ1qX9Dc2No6NNfbzSChLFsMvfn75"
    "ujlMouwZOtFXCgIq6x1ZTAYT8XqhZwucqayshNNmosPWm0BfTN2n4VsE8Ud/7UynjRlyG5gBOQayEsbEcnDjuaEFoxjxAXEB"
    "cGCw7m+JyeoLFCxcUCne06AHzL1DjyiJNEx00zl5ep30eJY4Y0FtMK/bQNfTcWf4YJBypiNNtrSqILcCPkoGF0bXSnm7EmAu"
    "xfe5E7ykcf78pavmL20cm+VCoRwQQuE7ly9cN8c+NTxRRjHE85wwNjOCgzt+Gn9uq/OQSV8cVOomfaKU7h1ER8LiGfPMWVOO"
    "lzC6IQICCwW1rQkdwZNFrjb3tst4bzXl+eQ0T6ZDiYP4gG7I8o4t77p2V5DAgyTwZBIgwIwm9rtIqNd1B6RmWnpkDFIYLxuk"
    "Zrf3CgIE9He9YZcdVI2tmk9aY2P/kqkAIRxYt3D5nc6ZPd3tPjIQpqyee2DocAd/Zb3pyGhoCSoVIQBiOSPKrXn7SAlpF+GH"
    "NNQrHJ7ZTHaI/Sn0mQI1gPEhC8Uex3TcF8RsEkjnZYDBNOlyB+j1lWvwM7UrpMigZbrCg3aEtUqiJB/j10reAQKcdUQq/Cq5"
    "wpCIBOl7UjrrPWl7W2XVALHnTsYQRvrHqiqqHprPWmO/r0SoqnIiD7Xv+dnydW//eNgBRq4V+TEEZOlsxZDnMTfyaLd0bino"
    "z19IzkW1Zm61iDwAP3S2SbsYplaXlhO3qgQpjlZYdMhFfmA4swDq5Dxl78/BvXaxahVEIES0bzg4UKxuAp7ECtFXgbDS5zrL"
    "pop2ptKg3zNoE4WVWizvrgd8aYYiAaiXZbpfDaJWKRCc3sAV6z3sg3CErcynWNW/tHF7RdUnQDUQIKwaUwGhanvX2llj/f1j"
    "a6k8mH3N8uW/ez8nKvb4GQ4Rbb9lq1CCd15CoSIVvPbTZIkGhPMZMhyGaqnBUZiOi7Wb8wI+uGVJhnaLi8ygdh8wT2MNfwtp"
    "9ZqlgvQARDK5I4n/1ewVGS2UQiilAhNPAysEBhLFvKjS93I2EoPOZ2IeLQmnaEdTebbCqBypl4CALzCY9sBjAiwhIgIBhnr4"
    "XjKLVbsanwNlsKSfwgBYQheBAD4ZtoEQXjsGXLLx+Oca+7cTfvDiNQsXrguEwxxn6E5pPtUSqbyjQslY5ndqNfY4YyZmC398"
    "LoNPIaz9fAcWr5cm7aNY7LEPcfd29bOZbmHjBZG1PmGqZAFCkJCISwQAbRW0UmWlntgswCWoPaFPBgQdYwxx87Mhz57a9xFh"
    "wKy4/UUxb2+zn6XzWdR1V2ACzxGXIhEIztdQrJwparYA1n2nfRfP37yxa5fiuQc8EJKwCjRDKHzj688GAj/5Um2YAqG2dgRO"
    "7b722lWNIzeGQgc//vLPFi5czisG7EuI+eSooCLFraOPOcOhxzsEx7FHSPoMEBVxwIsuVnJFgTLW04GhsHI/LmkSg/EwiQAA"
    "oe6zP2nYgrnVSyLYFWXAYOh1HZrr/WjqKwcCR9Qn7N7EdO/lCcpZizrPEfAsi5Z5nO8Q+c4LzhUMB6wabu/Fiz70343Xwuw/"
    "BCRhO6aLu69tHLsx/OL/XL7s8mXL7v4kAUL1AgDCKkokRwAl7/nnn61bBwLh5VqeQ4b2JL6mMsHIpBoGBwSQUONEJBA+7HlE"
    "gmoZCJwq1KkQrFEAQfAOGFifR6jjTAEUL7fAk7y3RXyCIKEqHBAwiksCWrxAcAwSEQigv50JQPXEqWLIFoYIBPiMDxAMnS6l"
    "8kBw8c/RbZFHBGCsuzfh9UyBMH/pCCBh7Uh/Y/+urrUVZwe+eMfJP//55XfMqrVVw65Vu0F1LN1eVREK3APSQBYIYEG+wwcI"
    "OVsiOI9IHTNRbVD3jsH1+AklIPCUERvaMMNlgcCGJkO8v44ForvK3uHpwtDrMRXZ4owX/DOfUgPBQYKu4K+mZfvRglhx64YA"
    "AsPDhaGtwQqQqSpZIjCHRpHDtgQEpN1g6ZJGtAQiFIhohc5fkHlcO7Z7/vzn5sNSr6JJKFhMzJsXmHvHF/8nMDtsA2Gkcff8"
    "pUtHKkIH37UOUABt+Z1tYW8QUm00NAzYEsEBAuh4svITEhAsvCipFPHoTJeFW3gqJgcCOF8QjnoC8Zd0iEPUReiMItEXyciW"
    "CwS8uOt4kSABwZVInDNUJ5/SOCnI0xkRCu6NTKbbFBIBw3Gldoxu+APBGUNRPQgiAYAwwfKSqh5qhBleOr9xbGQtCR88+5Of"
    "BJ79anj2v7xQEaplZLE2PHI8AOETVYCD5VgtLFx4DwFCVRcXodgxdKHCbohi55Zu8O4/ZgExUuuZpJ2OOvHMqouVxxCdJd3H"
    "endV0BNaJKK199nUuqz4wJ94nnc+8NYXZ4Pp2ZTmJxGoN8sUvVvsoymb6hMnhqFUCrxcwN8UJxo9phsypQBfMyZfvkA4Xytc"
    "qiAuRrqJk9vAEUY/xLxJuwAIjcAXsYd5SXj2w3fccceyY4+dFQ7PCwQOUiB8DjgCKIZP3BgGL9Jn7llORMLyd9WGu8Ce3OUg"
    "4VDnuNKATOkeIGC2U9BOEq1cu2UUQABjKpHoK5USAxCgm9hvL1fPKkkkEmyx289vTWDxUtQ5IBBD1jTzFlxtmaZLKMipbJPA"
    "7gfzKiDovJM8qJ1H9b0959lEMjdA72wDgZ6oY0ovx13N/KAg5CynM+43GTplrzIQCJfcrBU5ZecFAnbFGB4gkNvERPOx+17G"
    "9Lr6IcQwsr2ra+ShsRfCAWCJJ1+OaWLg2Lu+OIuSxVnEamjsCtW+/LuFn1nI2rvaQiONS6k9SVtvSpkg0CzzPcy9a6io8CK9"
    "Hikkgn4O2oxb/GonCC0BIdGAmrC/zuC+aAKS9WHkKx0gwGSDh9pKpuLPdBRaehImCxMwEZ7lphj++TFdAoJOuW5QlAhsaqk6"
    "QlcXWiCsaIrq2SBKD9yEAwYPBCxA0slUS8uD9CO8SICbdfgAAT9REjX7A4EaPJJEgIeFeE7EBUL78A4n/Gxnp1bdGHr92GWk"
    "Bdo+efeyn5/8SYcsjgCLCNXOu2b5ws/8LcXBPXNqbxxZtRuzC4ckZJQkoV730C3mS2YnPIZWAvSLDAQxPqEGAp7CjMmvGjOm"
    "/ZfWknf8mrrtL7BTjpqaKRLsz6wXaCADqsfWMwhnV0oExkuoK7Nk8uwUe6dJ/KDHMX1sHMRYMAK11/OxUfKPneAvoUDwCATs"
    "mOv5oGN8KDhCj6nwyeHH3+nGLwPaY1e86uSnYs9xFyh7IIrPUiDc/dXZc5ctO/nkL7tAAH9j6OCdy++x5cHCde8PV40JjsjQ"
    "p+vkSBvSOhK6wKqZSyilFSxZ9xmYKktAAD/Thd/73v33f+d+N1ZfQ5UtD4SP/o1WNF0hSIBABVKlLbjXYI8vJHFAShvCgXNU"
    "3GK6C8fkRBqLmXJ8j+tjwVlUCiDQO2vtCVOwJbCpFGH8mLOA8sRVGQwSj0dGXDOGeUDTVECg12Q/pgsuMg4IxIdmCP42+zoz"
    "4V4W0Hb2HnScAFUjx4OIb+x/3wsVgbvuAv/BXYHaL78dft3tACG0q38WGI7r1i1fjhkC/vOVcKgKeyNXEU8k9TKvl73MIDpd"
    "I4b3BicxmVf4djBBkiVC1sINy3QbawogaFrDx+xlQK13CImiMwVXkq4PtGs1UYdRoYzpaHEzJyj/9rwIBC4+GEPlJAKiqYRx"
    "S1AsZimOv88SnIEkSSDi5D2iepEn6ETMKSSCrovxTi8Q/kkr5nVDVznpDX2QA8LEHCc1ackYdi43rnru+FkVX3h47tyHH577"
    "YnjW3N8f+/uHqflY/aVwxW/AgzDvK59/7ZprXnv7a9e8ds3nv/KeMKYXOEblAOG2kuxbDNruLQEIWB2fYumVsuvFMFeoOAI9"
    "twbnInT4SIRLM5nkMFOfttwBP+Xmb3uA0KPVCJYBC39i+iXGmOtNXQiIcZ0fiDuz5yWLdjAY1aBmkWF8fwPI+UJWlAgJPhHi"
    "Iq0pIQIBiMVKPyBUCqkYAhBcD4ic78BoKwNCbLUjD8Yad2PTcLtjCN6CMXLL6y8sef0gzlBaXP0liplb5p398YMHz6aNpCZt"
    "h2wWjiyqgECyBgx7mfLTvkZ3AiJCN7ciFRBcs/zX9HG9QPD4niirOwni/lnxVF9BDABpHecwf1Myzim2iONdFmIY9p0zSrKI"
    "fztZAUhrv1S3zxHjIAWMpdUNrZDDPUiMXKTE2Lv1IJUI7mfUJrUHCCtdU83jZMZqMmtbsloAZVbTVDQIQjfO370b+5hplJlv"
    "cOAqDIQPK05UMZOj3+WKFWd1X60AQr0rOPWptDOJKk0qLmfh4rgPEDzCBVaM1UCBwBssSY/6gkSn+5Lp9PN1G5DX2DE8QKh0"
    "ud/1yHEU8kDQBSCgOk6rwJ8iZrO6KyOwKdEkjBjc7VLxoVICEAw/H5oIhKhIxHnT1ya7QQaE+tUQXwyFIYy8i+j5WaAiZm27"
    "6vgz3HbVtm1XbTvjdGhnbOMOn7HteHxmAQlHV3Vt5zLbzuo+QQGEOk4iTKFhXX++BAR+Tiij85MInGcPy0CimVyLRQoj0zRX"
    "hORQ/oAdKTYE5yJjfq1KicADIcp8/S4QbkfOpNo+xATyfq2YjWsWeSCUd6jzQIjnBWOT81URR5st+zAQwrXhMAbCb7BDCbxC"
    "S7bNra4+nWvV1Z/6FD2y+HRPq4Zz26poFLuCB8J3FMlSaddjowgoyw2W8UWSarD1KnYDpJQcQRF0Alb0jx4g4CUWkcpoiDSt"
    "EZdm0RQRIJp1znz7A0Fjvm0XCH9kQHADcHpSAkKdHxCErAglEOwwdNATqrETrOhf3XCTdgIoiYFQC1iAjJRGwve6flTtne/F"
    "NgIkJAAWftQV8iSwhc7qPlEGQoPlDwRlyz6iAoI7wVOSCJU6JWIXg2qYDAhBuUxFzO0hP08TFVT2HZMBIcqSKmSJ4AYU9OS+"
    "ckAA6tz6JoCAU4FEIFgW1pTuR9MFmhHCA6Fi7cguSFetWlAtzzYgoLpadRzaj74QloGwzwuE84k/Rz8SIBDhrbIa7DhevCxZ"
    "dMcF4jLYk5cVQ0xPajWSy+vqws3xDm8CuUg6EqdkeeGEMwyiaDKOkHS1C88RuKtLUi5JQnyMCUk1+APBUQ12/NlZRT3H8EDA"
    "ZBcxiRCbU1tb21aL55LyPjUQ8NKXj5BD1QskIDwuA2GlB85TaVhuyUCg+YUGCcmhyYBAEFNPYo/xrOiuqJNqHQv1l0JdTLr5"
    "GW9uD2/7pVC34/Yjz5NtIYKpLBASQjQShBGOZzpAIHn3XxOAQOKdQi7SUzIQVJyRBwKYK5Y44Nav2i1Ov8EPVjcA5mMv4GBR"
    "GzeXH/YBwuk+QPjIgrAnDF3xttKFMllMlkk+VDdM8WT3M0vwNXMsm7tGaykvYhI0yLPZEr/d8iSfaCv6WN7zAJdjmsrrQhQ5"
    "8TUU2+IGtFzq7QsEwGAxb/C2ov4I9iNYjnOK+pN4XywK4lxZgTCNK8miUVYioGZTtBrrEdM4rkjYiZhDCYCwaFHt5EBYvHix"
    "zBzg0GIFEG6TMuuRTf+PAAgYrR4gwMpIZ0lL9HT4BJ28bc0GmpVCss35K/l8tOhKDdKb19hKp8XW+zTZjzO73q3hNA8XCLhL"
    "JG3EFwgXaQ3DQkwIJyF+1M7atoFgXt8E6tNuF2OcCK2E1FYD1zsvEIgHRDw7CEVerjSh5goRCQGttXd2G1MNrC2YMhDoTwUQ"
    "cCKzbA7ZxsuUgQB5dZIdnEEtT4yfGL8f8VK0HBCMC+xUnGZTyNoj6QTUi4Nr2e+znOxZcAJvZlrn5ryQu6xn371xY0+fzicY"
    "MD+zGghBKPRH57jubrtm43yiLnTerwKzFw3aBe4k3ump6XKBwLpUX2eW4whBbat3KK6b2Lh1DW+HG9RBAUA4d/gXQBKmAIRy"
    "qsHLETZJpYERbdziElen1Cr1B2XVsNG55T9EWL1/edVg6AeQ18o0cAYYZCaSatAakjWZ6tMNx/tt0MTUoCSPDF30NNPBzGIf"
    "pQoIJLjXcI7rLaA3IOUIaCsXeaEqpoH0Bn+oIedlU82Y2sb42BWkMjZcb8gJCly+Z580MKYn7EfzrIIAhI7cHnAi8AagL1ms"
    "niIQQuHTMt7gY5S4VLlV5IYf/TLV4e9GQhaFi65DXI1wVCkRDE9aIhX0TvTTTVGFsusCVePtmTzxttiJhjqJmkEeX17hyjW8"
    "HmfsZ0YSEHC2G0Ltp+SErCXyDNDnIHN526IdupPvfoyxy0c6RZuAeH4ukoAQ0667QOEudDhCq+5TDcJxXwP7maM4MWXofZ71"
    "PHWJwOAgF8L1Ksowe3QxfOfxznBay83uwksnKfKdRH2GtNjExnPdWIMhGNcGH+aGf9RROoFipqdcWjezdcc9+WTmW5boMASW"
    "0IAz6LBA8Msp5PIKjcRNFAjC9D3/zW9+sz5hyaKbRH+DXMqiU7SYPXPjxMTG5oSAMvKjZGcocVIVrCEcMmVBJx44GAhBol4M"
    "MQ3IkBPhdBMQiyBV7bgP/alAkFTDrZ1xCQiCRWusMfu+7XHT4X/3fesHQh5b8kICBFUtEOSR9BVJJFoCwgUX8NlhxJuMaOmg"
    "5Yy7Lkc7eSqAC2fAz1joU5RCqf6bwd2IS7c1ZWJPSqSouNzoTRoS0cw5sbDBSYBgukCglW24ALvSUAAB7J4UTYKeBAgGpsaR"
    "wPla6/BZRxsIh6WiN2RzI0eK1X3QI8nxj611Yt5K+iS2jL1JnXRFmLkCy2IWcsH+bdBcYwiJglDNGKH+Vkc9qYHgVK/sJWr8"
    "dnMyxwcDVhrHx+J8PYOfoxMEQhMz8jvSum8tjCESOlbiwksEmEHsDLrBMuVIGw3X5TzZE7pHvPE1BQH4gu7vho4yEFZfKaey"
    "t1ue+pWGLP/M1FtbaBYz2bLfUASdOMFMKqVEIMDxd4KtbAg63VzPeH1WDPkZaiDQKBUuw/Okm+vSPhj2sY1gEMZ1w3XUeLOS"
    "3aSAHmQTnJTpTd3zVOkbduJJyi55c+MTFAiQ77nX1D3Z7xQI9+Wpw0koCpVrJ7AePI9UOg3de3SBEDrUKxW41JA8DH5cmp0Z"
    "5kv2Ck7OKQXCBkXto7PkDGL7RCSJMGrbB+4IWDR/BGeAKXc04VU+C2wCSU+ZYoTJ0NXDScvzZSB4J4B0u54LQdActkrexyAU"
    "atufsbOluYilTaFI9bCIUQIEOnAefiMk1XDAiWGOoB0zfFSBEArt6EYyEDZ4s6RQK8cO6fpuxl4WN60Q6wplYiuHCLJyW1g0"
    "jUGtDtkfcifqFfLCMjz0bsmJuDCEClqa4JsUk5YNRcqLfX/QsxwQpPJ998v63PraIPZhGW59uJPIarhSkvzPyYyUgUA8dSY7"
    "IgIh7SQlKeqnRG6cRrga+oTuXxxdIODdFqVtiwbFKbygCXuYXJziLluw/tOmXukICpjn8kCo1EkR7LliZmkC2emRNH0dnzyO"
    "RJiA/lmG39p2tDgN05O4ubSA3AkWAtM6jiPF/QJBnAmQTyE+Tb5HMJtU6TW4ZrzH9niLQKDbIES0GxK88cGqobFe4/u8xtDd"
    "akyPtAKkkR1TkpuOKhBweQvSykoEw0g3kDgr2xeEbgACGaNa0uQmFQNBy6icDc50lBpAOY/z6aQ0z7PZJWfkhjF7Q4LBLC88"
    "FCWwMMD5HuIydtcUWbZrxAkz+Foqki4w7ps65H5BM/LuKeWbaWR/CM+3DARiNbC7bHC/l34Kl4SM95WJV5MH4oDQQjbKaO08"
    "62gC4XC3nMvupDBzRbxESHCaK1+ETL6UKXhfktgrooSAC4SL8L35ScJAYEHcSptbvWKn8KOerLfgRCpYZrNFM2nca/46De16"
    "8jOdTugmX8qG0wU2Z/2MANtz/f2i15zqONOcBAguDmq0CREIE06o3FMlgEVF+4CoBdJcK/WJKbhpLBFAQA19eiqexakBIRQa"
    "blUVwN4kelaK+PVRaa7QAGDZTrJHdM7Rm8cC1/LFgW7voZQQRpxEA1OOYU6u/FeWfICkBAMp/2lLsx02TJqcAjCtdsS3etPk"
    "xDfmCCjhZw7am+y1yjm9HT57hTnc1S2rAzKU5Qkf7Dy00g7ombrh2opEVKC0p4aBbw05oRIvjeiGmzuHjyIQDnd3yCHoIOek"
    "IxnncTwxrQ4QdEqnI+AGNjmpa+FtEnNldj/AzhlOEdghthoa7HQ9LVbcpa8odamvoY/dK+52lIO2bYt9d6ZnQ71CgveGYrXG"
    "YjyGeqMDU687V97+M+oNZwi1r5XEFxb1OmMMZ78xJ+GhZLrfZ1pkH5VmPmkTLym+bbBMDggZFGC3+eGbUg2LVS7m3ivVO6qd"
    "a7k7AZItTICmJkwnw8NMkCAhSvHWHCkJSlmmf6pBBw0JJNxiQZOlH8T7bIJgGPyWjvD7swk5emsfSdysOWnJxLyj/BEMCYyl"
    "KNvdOQpux2a3oz+Aci3w6d78LVP3OhGc+lYLdtdT7A0NgnFrVlJR9v++PSiq2a36D9Yw/W5y1X9kNy1d8K5AyWOaKcdKtjVN"
    "MEq7D+CLkE0Lnc0o43QzrSBmCZ7o41TAgAPT1SQMHXIVw+GS3745eELJ1mW6niMFJFEUHzCdrQ4GbclhMg4Jm1qRFG+2PaZC"
    "5JoDGxw7jFrkcKyTJeaSGjb4NnyjXJNnJ5zi9bqnoJVlyP8U8amLhbTdGdNagaSlTMcSTppFxLbBNU3aDd6XSMaahbeUu5AW"
    "6rJeP5JBhFOyXRP34kBuUaS9Z4IdiicVeyRzK8delkAGnB4a8GwPhrRf9dlwM8Fas3deRUOrK0JHLBGqFxPA8KohfAjiTX67"
    "6/VYrGKI7VUFY7lhgNSAQ1LQILd3JJMAOVZvhFIJd5G44R64zwq7KAS2KNbpjUqOnQ4AYhsU5DyhD9BKTRnLjf3ZOtfCW4VH"
    "hQ2OS7QzpjUoV2412RnClrMpdCFpmabu3ezPShbjyHdbbiwHBxNcCRj7IOwHrNiLv9liHarnu4rI09LRzdmTfoItS83cfd59"
    "kUGGlEy2A1AK2ZtyQ7JA522cRFg8RSBQucCphnB4dZlNuVE8mYa6xXfy+zA2ZUpwqBQrcCttkFxWt9M1uJuuOzA6WofbO+tY"
    "Gx09cB2fZtoUS6etdKnI7VqOzkvCzdOjO5FqG+yG1HrL2coC75OQ/mmTvIk6bGgOfUnHFOsZ1mexjpyMczWn8cx61lXWYsVf"
    "NqFJd2dHK5KJvFssobOvlNEHF8LopJODUupPIYNP1PVwANkfS/fBMfVu8k2Z9EBfXzrWJLy4IzZ8WejNAeH0T33OBkIovGMg"
    "XnZ7c/TEuGczfIjYx4VDUfIehZYmaX87T1PgbNz7IQTHEPLbpx9ejxCrr0vgloxNxH1mCzXEffbvx0u5nT5PVEiIV3QTTfq6"
    "BoRSsQN2b14hiyWq2nYGP1QBqbadhxPSsKHxuP/bB+D6OPK8uAMNbbIth64zIHO9Ws5Mk/lBNalwOWNWmCEh/HjvMWU2N7ch"
    "UoPkN13wmjAovexCfDuLLeAjSCt7I/v7IsEy78pAz3zje/fT+VK986XsRCrqIKLya2Cgn1N4NQyD0ObNV9tbgPigL8jvDTHJ"
    "y0Om0vsoEl/l097tvAK2SyhsK9+g5u1zpy6qJTVzoVDvEJr0rUXeUcGHkPd9J4q3GkWDYlOIG0lOBBXfx38zB69IxO+lLKjM"
    "+54UnRf6egQvx43yrysSQa4Ynan2xqeD7jukkOedThF0TOdtzkbLbzx6ySWXPProG7OWdHUt6Voita433ngUX/KBD1zy1dmn"
    "Nixqa4P013Do3m5UTiD8f2y+ikb787xtjLbon/V1f7HhWx1dD5UOtTC5vi/uCUMtREMDdlEtaoO/CC2C/Nd7O+Mzr/vT3uov"
    "AAU+OtRrIyHsSWxWvKMBoNC2CMDQVgs/8K/aw50tbzV5MNOUrwQGJDDTIRQmBdLl3/sWpnDBv9owDrC7faZNg5eEgwV/5fAh"
    "mP0QLZOftNlJ8GR/hcMDMziYJkAg2gF4Akwrpn7hI3hxfCg0p7NFWzkzntMDCFgmxDp3gKhf1ECsgNBUsXDWnM7xmcGcPkAg"
    "LtXO1bMxDWyjUmFKYJjXC+9xis6M5jQCAjDGX3b3vnfRImwQgGnIwFBWK1Qc7owhrWZmMKeVRMCvIYx1bvotRgJJZWmjOyz5"
    "iYZQ+Nbe7hZtxm6cbkDAU4pah4b/HTuMGkiUjvgNCRxsRDiwCIUeX915JdJm/EjTEAgkwPV07g/v/S0A4cJ9iPphG2hbxBrx"
    "NgEMNl0x9KA2Qw+mJxDIPg3PTJSGHzgVa4cLBU88URcNi4iAeHX1FUOtM+Jg+gKBReuf7s4le04hTAHdtG/fSSdeXLMPUQoJ"
    "bfamPwyTFJMZdjCNgcCg8FQsl8u99I6nTmI50EQYLFp06uz3PpDrzMWwK7EmODOI0xoILGtm33hmqDv34z8mb3+p5z+gvfTS"
    "Aw/MGe7uHmr9DtJmpMFfBBDsrBnIG9sZG8qxlkwOxVpZ8tMMDP5CgEDTc9jvjkI8Hi902MQxEpmhiNOp/S+CCxtfqqwp8QAA"
    "AABJRU5ErkJggg=="
)
PROVIDERS = ("all", "onprem", "gcp", "azure", "aws", "unknown")
ENVIRONMENTS = ("all", "Production", "Preproduction", "Dev", "DMZ", "Backup", "Unknown")
CONNECTIVITY = ("all", "Connected", "Disconnected", "Expired", "Unknown")
MDE_FILTERS = ("all", "failed-extension", "missing-extension", "unverified", "healthy", "unhealthy")
SEVERITIES = ("all", "Critical", "High", "Medium", "Low", "Informational", "Unknown")
VIEWS = (
    "inventory", "findings", "actions", "resource_details", "posture",
    "attack_paths", "software", "controls", "compliance", "vulnerabilities",
)
RISKS = ("all", "Critical", "High", "Medium", "Low", "Not evaluated", "Unknown")
FINDING_STATUSES = (
    "all", "Unhealthy", "Healthy", "NotApplicable", "Active", "Resolved", "Dismissed", "Unknown",
)
ASSOCIATIONS = ("all", "arc", "context")
SEVERITY_ORDER = {
    "Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Informational": 4, "Unknown": 5,
}
CAPABILITY_MATRIX = [
    {
        "feature": "MDE integration / agent-based vulnerability assessment",
        "scope": "P1 and P2; supported OS, onboarding and healthy endpoint telemetry required.",
        "caveat": "An extension in Succeeded state is not a verified healthy MDE sensor.",
    },
    {
        "feature": "Agentless machine scanning",
        "scope": "P2 in supported Azure / AWS / GCP environments, with platform prerequisites.",
        "caveat": "Not generic agentless scanning of standalone on-premises Arc servers.",
    },
    {
        "feature": "Just-in-time VM access",
        "scope": "Supported Azure and AWS VM scenarios.",
        "caveat": "Do not promise JIT for on-premises or GCP Arc servers.",
    },
    {
        "feature": "OS baselines / file integrity monitoring",
        "scope": "Validate the current support matrix, OS and required extensions / MDE configuration.",
        "caveat": "Buying P2 alone does not verify feature readiness or correct configuration.",
    },
    {
        "feature": "Defender CSPM / Defender for SQL",
        "scope": "Separate plans and licensing; SQL coverage also needs appropriate SQL onboarding.",
        "caveat": "Servers P2 does not include every cloud posture or database protection feature.",
    },
    {
        "feature": "Secure Score / regulatory compliance / attack paths",
        "scope": "Collected as explicitly labeled subscription context; CSPM/platform prerequisites apply.",
        "caveat": "Not Arc-only Secure Score, automatic certification or proof of an Arc attack path.",
    },
]
DEFENDER_REFERENCE = "https://learn.microsoft.com/azure/defender-for-cloud/defender-for-servers-overview"


class EvidenceError(RuntimeError):
    def __init__(self, code, message, source="", http_status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.source = source
        self.http_status = http_status

    def as_dict(self):
        result = {"code": self.code, "message": self.message, "source": self.source}
        if self.http_status is not None:
            result["http_status"] = self.http_status
        return result


def _utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(value, maximum=240):
    if not isinstance(value, (str, int, float, bool)):
        return ""
    return "".join(c for c in str(value) if c >= " " or c in "\n\t")[:maximum]


def _get(mapping, key, default=None):
    if not isinstance(mapping, dict):
        return default
    target = key.casefold()
    for actual, value in mapping.items():
        if isinstance(actual, str) and actual.casefold() == target:
            return value
    return default


def _enum(value, choices, field):
    if not isinstance(value, str):
        raise EvidenceError("invalid_parameter", f"{field} must be a string.", "parameters")
    for choice in choices:
        if choice.casefold() == value.casefold():
            return choice
    raise EvidenceError(
        "invalid_parameter", f"{field} must be one of: {', '.join(choices)}.", "parameters"
    )


def _validate_parameters(operation, view, provider, environment, resource_group,
                         server_name, connectivity, mde, severity, limit, offset,
                         risk="all", status="all", association="all", resource_type=""):
    params = {
        "operation": _enum(operation, ("report", "query"), "operation"),
        "view": _enum(view, VIEWS, "view"),
        "provider": _enum(provider, PROVIDERS, "provider"),
        "environment": _enum(environment, ENVIRONMENTS, "environment"),
        "connectivity": _enum(connectivity, CONNECTIVITY, "connectivity"),
        "mde": _enum(mde, MDE_FILTERS, "mde"),
        "severity": _enum(severity, SEVERITIES, "severity"),
        "risk": _enum(risk, RISKS, "risk"),
        "status": _enum(status, FINDING_STATUSES, "status"),
        "association": _enum(association, ASSOCIATIONS, "association"),
    }
    if not isinstance(resource_group, str) or len(resource_group) > 90:
        raise EvidenceError("invalid_parameter", "resource_group must be at most 90 characters.", "parameters")
    if resource_group and not re.fullmatch(r"[\w.()\-]+", resource_group, flags=re.UNICODE):
        raise EvidenceError("invalid_parameter", "resource_group contains invalid characters.", "parameters")
    if not isinstance(server_name, str) or len(server_name) > 80:
        raise EvidenceError("invalid_parameter", "server_name must be at most 80 characters.", "parameters")
    if any(ord(c) < 32 for c in server_name):
        raise EvidenceError("invalid_parameter", "server_name must not contain control characters.", "parameters")
    if not isinstance(resource_type, str) or len(resource_type) > 180 or (
        resource_type and not re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]+(?:/[A-Za-z0-9_-]+)*", resource_type)
    ):
        raise EvidenceError("invalid_parameter", "resource_type must be an exact observed provider/type or native kind.", "parameters")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise EvidenceError("invalid_parameter", "limit must be an integer from 1 to 100.", "parameters")
    if type(offset) is not int or not 0 <= offset <= 50000:
        raise EvidenceError("invalid_parameter", "offset must be an integer from 0 to 50000.", "parameters")
    params.update({
        "resource_group": resource_group, "server_name": server_name,
        "limit": limit, "offset": offset, "resource_type": resource_type.casefold(),
    })
    if params["operation"] == "query":
        context_view = params["view"] in ("posture", "controls", "compliance")
        if context_view and any(params[key] not in ("all", "") for key in (
            "provider", "environment", "resource_group", "server_name", "connectivity",
            "mde", "risk", "status", "severity", "association", "resource_type",
        )):
            raise EvidenceError(
                "invalid_parameter", "Subscription posture/controls/compliance views do not accept Arc filters.",
                "parameters",
            )
        if params["association"] != "all" and params["view"] not in ("attack_paths", "software"):
            raise EvidenceError("invalid_parameter", "association is for attack_paths or software only.", "parameters")
        if params["view"] in ("software", "attack_paths") and (
            params["severity"] != "all" or params["status"] != "all"
            or params["view"] == "software" and params["risk"] != "all"
        ):
            raise EvidenceError(
                "invalid_parameter", "software has no recommendation risk/status; attack_paths accepts native risk only.",
                "parameters",
            )
    if params["operation"] == "report" and (
        params["view"] != "inventory" or params["provider"] != "all"
        or params["environment"] != "all" or params["connectivity"] != "all"
        or params["mde"] != "all" or params["severity"] != "all"
        or params["risk"] != "all" or params["status"] != "all" or params["association"] != "all"
        or resource_group or server_name or resource_type or offset != 0 or limit != 25
    ):
        raise EvidenceError(
            "invalid_parameter",
            "report always exports the complete configured scope. Use query for filters, views and paging.",
            "parameters",
        )
    return params


def _plain_text(value, maximum=8000):
    if not isinstance(value, str):
        return ""
    return _text(html.unescape(re.sub(r"<[^>]*>", " ", value)), maximum).strip()


def _safe_link(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value) or len(value) > 8000:
        return ""
    if value.startswith("portal.azure.com/"):
        value = "https://" + value
    if not re.match(r"^https://(?:portal\.azure\.com|learn\.microsoft\.com|support\.microsoft\.com)/", value):
        return ""
    if re.search(r"(?:[?&/])(?:token|secret|password|sig|code)=", value, re.IGNORECASE):
        return ""
    return value


def _native_risk(value):
    if value is None or value == "":
        return "Not evaluated"
    return next((r for r in RISKS[1:] if r.casefold() == str(value).casefold()), "Unknown")


def _is_actionable(finding):
    return finding["status"].casefold() in ("unhealthy", "active", "new", "inprogress")


def _counts(rows, key):
    return dict(sorted(Counter(row.get(key, "Unknown") for row in rows).items()))


def _group_recommendations(findings):
    groups = {}
    for finding in findings:
        if finding["category"] != "Recommendation":
            continue
        key = (finding.get("recommendation_id", finding["title"]), finding["risk_level"], finding["status"])
        group = groups.setdefault(key, {
            "recommendation_id": key[0], "title": finding["title"], "risk_level": key[1],
            "status": key[2], "technical_severity": finding["technical_severity"],
            "category": finding.get("recommendation_category", "Unknown"),
            "records": 0, "resource_ids": [], "server_names": [],
            "remediation": finding.get("remediation", ""), "portal_url": finding.get("portal_url", ""),
            "provenance": finding["provenance"], "reference_utc": finding["reference_utc"],
        })
        group["records"] += 1
        if finding["resource_id"] not in group["resource_ids"]:
            group["resource_ids"].append(finding["resource_id"])
            group["server_names"].append(finding["server_name"])
    for group in groups.values():
        group["affected_resources"] = len(group["resource_ids"])
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Not evaluated": 4, "Unknown": 5}
    return sorted(groups.values(), key=lambda g: (
        not (g["status"] == "Unhealthy"), order[g["risk_level"]], -g["affected_resources"], g["title"]
    ))


def _failure(exc, provenance):
    return {
        "status": "error", "provenance": provenance,
        "coverage": {"status": "unavailable"}, "error": exc.as_dict(),
    }


def _highest_severity(findings):
    return min(
        (f["severity"] for f in findings), key=lambda s: SEVERITY_ORDER[s], default="Unknown"
    )


def _enrich_inventory(inventory, findings, provenance):
    by_id = {row["resource_id"]: [] for row in inventory}
    for finding in findings:
        by_id[finding["resource_id"]].append(finding)
    for row in inventory:
        observed = by_id[row["resource_id"]]
        reasons = []
        urgent = any(
            f["category"] == "Alert" and f["severity"] in ("Critical", "High")
            and f["status"].casefold() in ("active", "new", "inprogress")
            for f in observed
        )
        high_finding = any(
            f.get("risk_level", "Not evaluated") in ("Critical", "High") and _is_actionable(f)
            for f in observed
        )
        if urgent:
            reasons.append("Active high-severity Defender alert: analyst investigation required.")
        is_arc = row.get("resource_type", "microsoft.hybridcompute/machines") == "microsoft.hybridcompute/machines"
        is_compute = is_arc or row.get("resource_type") in (
            "microsoft.compute/virtualmachines", "microsoft.compute/virtualmachinescalesets",
        )
        if is_arc and row["connectivity"] != "Connected":
            reasons.append("Arc is not confirmed Connected; endpoint visibility may be stale or unavailable.")
        if is_compute and row["mde_extension"] in ("Failed", "Missing", "Unknown"):
            reasons.append(f"MDE extension state is {row['mde_extension']}; installation needs review.")
        if row["sensor_health"] == "Unhealthy":
            reasons.append("The separate sensor-health source reports Unhealthy.")
        if high_finding:
            reasons.append("Defender native Critical/High risk requires owner review; technical severity is separate.")
        if is_compute and row["servers_plan"] != "P2":
            reasons.append(f"Effective Servers plan is {row['servers_plan']}; review the intended baseline.")
        if is_compute and row["sensor_health"] == "Unknown":
            reasons.append("MDE sensor health is unverified; extension success is not health evidence.")
        if row["provider"] == "unknown":
            reasons.append("Hosting provider/location is unverified; N/A does not mean on-premises.")
        high_gap = (
            is_arc and row["connectivity"] in ("Expired", "Disconnected")
            or is_compute and row["mde_extension"] in ("Failed", "Missing")
            or row["sensor_health"] == "Unhealthy"
            or is_compute and row["servers_plan"] == "Free"
        )
        row.update({
            "observed_findings": len(observed),
            "highest_observed_severity": _highest_severity(observed),
            "recommendation_records": sum(f["category"] == "Recommendation" for f in observed),
            "recommendation_status_counts": _counts(
                [f for f in observed if f["category"] == "Recommendation"], "status"
            ),
            "recommendation_risk_counts": _counts(
                [f for f in observed if f["category"] == "Recommendation" and _is_actionable(f)], "risk_level"
            ),
            "distinct_recommendations": len({
                f.get("recommendation_id", f["finding_id"])
                for f in observed if f["category"] == "Recommendation"
            }),
            "priority": (
                "Immediate review" if urgent else
                "High priority" if high_gap or high_finding else
                "Verify coverage" if reasons else "No observed gap"
            ),
            "priority_reasons": reasons or [
                "No gap observed in the collected scope at the stated time; this is not zero-risk assurance."
            ],
            "provenance": provenance,
        })
    priorities = {"Immediate review": 0, "High priority": 1, "Verify coverage": 2, "No observed gap": 3}
    inventory.sort(key=lambda r: (priorities[r["priority"]], r["server_name"].casefold(), r["resource_id"]))
    findings.sort(key=lambda f: (
        SEVERITY_ORDER[f["severity"]], f["server_name"].casefold(), f["category"], f["finding_id"]
    ))


def _source_summaries(sources):
    result = []
    for source in sources:
        compact = {key: value for key, value in source.items() if key != "errors"}
        errors = source.get("errors", [])
        compact.update({
            "errors": errors[:3], "errors_total": len(errors),
            "errors_returned": min(len(errors), 3), "errors_has_more": len(errors) > 3,
        })
        result.append(compact)
    return result


def _response_bytes(response):
    # Match the sandbox's default JSON serialization, not a smaller custom encoder.
    return len(json.dumps(response, allow_nan=False).encode("utf-8"))


def _check_transport_budget(response):
    if _response_bytes(response) > TRANSPORT_BUDGET_BYTES:
        raise EvidenceError(
            "transport_budget_exceeded",
            "The structured response exceeds the safe sandbox stdout budget. Full evidence remains in report artifacts.",
            "response_transport",
        )
    return response


def _compact_action(action):
    reasons = {
        "investigate-alerts": "Active Critical/High alerts need analyst review.",
        "restore-arc": "Expired/Disconnected Arc creates a visibility blind spot.",
        "review-mde": "Missing/failed MDE installation or independently unhealthy sensor.",
        "review-findings": "Native Critical/High risk findings need owner review; severity is separate.",
        "review-remaining-findings": "Validate other indexed findings and old evaluations before remediation.",
        "review-plan": "Free/unknown protection or P1/P2 baseline needs review.",
        "verify-health": "ARM installation does not verify current MDE sensor health.",
        "restore-sources": "Unavailable evidence is Unknown, not zero findings.",
        "review-attack-paths": "Review observed native High/Critical paths and source-recommended breaks.",
        "review-critical-cves": "Critical technical CVE evidence requires patch review; native risk is separate.",
        "review-demo-chains": "Review SIMULATED illustrative chains; not real Defender/customer detections.",
    }
    return {
        "action_id": action["action_id"], "priority": action["priority"],
        "reason": reasons[action["action_id"]], "affected_resources": action["affected_resources"],
        "sources": action["sources"], "provenance": action["provenance"],
    }


def _transport_envelope(snapshot):
    summary = snapshot["summary"]
    counts = {key: summary[key] for key in (
        "resources", "servers", "connected", "mde_extension_succeeded", "sensor_verified_healthy",
        "sensor_unverified", "servers_p2", "by_provider",
        "source_observed_actionable_findings",
    )}
    sources = {}
    errors = []
    for source in snapshot["sources"]:
        sources[source["name"]] = source["status"]
        for error in source.get("errors", []):
            item = {"source": source["name"], "code": error["code"]}
            if "http_status" in error:
                item["http_status"] = error["http_status"]
            errors.append(item)
    if snapshot["provenance"] == "SIMULATED":
        scope = {
            "description": "SIMULATED 200-server fixture", "customer_facts_verified": False,
            "azure_called": False, "token_acquired": False,
        }
    else:
        scope = {key: snapshot["scope"][key] for key in ("subscription_id", "tenant_id")}
    return {
        "status": snapshot["status"], "provenance": snapshot["provenance"],
        "reference_utc": snapshot["reference_utc"], "scope": scope,
        "coverage": {
            "status": snapshot["coverage"]["status"], "inventory_pagination_completed": True,
            "unknown_sources": [s["name"] for s in snapshot["sources"] if s["status"] != "complete"],
            "sensor_health_is_separate_from_extension": True,
            "subscription_secure_score_collected": snapshot["coverage"]["subscription_secure_score_collected"],
        },
        "summary": counts, "sources": sources,
        "posture_summary": {
            "classic_score_percentage": next(
                (score.get("percentage") for score in snapshot["posture"]["scores"] if score.get("name") == "ascScore"), None
            ),
            "paths_context": summary["attack_paths_subscription_context"] if sources.get("attack_paths") == "complete" else None,
            "paths_arc_related": summary["attack_paths_arc_related"] if sources.get("attack_paths") == "complete" else None,
            "embedded_cve_occurrences": summary["embedded_cve_records"],
            "distinct_cve_ids": summary["distinct_embedded_cves"],
            "resource_cve_pairs": summary["distinct_resource_cve_pairs"],
            "critical_cve_occurrences": summary["embedded_cve_technical_severity_counts"].get("Critical", 0),
        },
        "source_errors": {
            "total": len(errors), "samples": errors[:1],
            "returned": min(len(errors), 1), "has_more": len(errors) > 1,
        },
        "response_budget_bytes": TRANSPORT_BUDGET_BYTES,
        "qualification": (
            "Native risk != severity; subscription context is not Arc-only. "
            "Unknown/empty sources are not zero risk. Full detail and embedded CVEs are in the snapshot."
        ),
    }


def _summary(inventory, findings, sources):
    counts = lambda key: dict(sorted(Counter(row[key] for row in inventory).items()))
    category_source = {
        "Recommendation": "defender_recommendations",
        "Vulnerability": "defender_vulnerabilities",
        "Alert": "defender_alerts",
    }
    source_lookup = {source["name"]: source for source in sources}
    finding_counts = {}
    for category, source_name in category_source.items():
        source = source_lookup[source_name]
        finding_counts[category] = (
            sum(f["category"] == category and _is_actionable(f) for f in findings)
            if source["status"] == "complete" else None
        )
    return {
        "servers": sum(r.get("resource_type", "microsoft.hybridcompute/machines") in (
            "microsoft.hybridcompute/machines", "microsoft.compute/virtualmachines",
            "microsoft.compute/virtualmachinescalesets",
        ) for r in inventory),
        "resources": len(inventory),
        "resource_type_counts": _counts(inventory, "resource_type"),
        "arm_resource_type_counts": _counts(
            [r for r in inventory if r.get("inventory_source") == "ARM/Resource Graph inventory"], "resource_type"
        ),
        "connected": sum(r["connectivity"] == "Connected" for r in inventory),
        "mde_extension_succeeded": sum(r["mde_extension"] == "Succeeded" for r in inventory),
        "sensor_verified_healthy": sum(r["sensor_health"] == "Healthy" for r in inventory),
        "sensor_unverified": sum(r["sensor_health"] == "Unknown" for r in inventory),
        "servers_p2": sum(r["servers_plan"] == "P2" for r in inventory),
        "by_provider": counts("provider"), "by_environment": counts("environment"),
        "by_os": counts("os"), "by_connectivity": counts("connectivity"),
        "by_mde_extension": counts("mde_extension"), "by_sensor_health": counts("sensor_health"),
        "by_servers_plan": counts("servers_plan"), "by_priority": counts("priority"),
        "source_observed_actionable_findings": finding_counts,
        "observed_findings_received": len(findings),
        "recommendation_status_counts": _counts(
            [f for f in findings if f["category"] == "Recommendation"], "status"
        ),
        "recommendation_risk_counts": _counts(
            [f for f in findings if f["category"] == "Recommendation" and _is_actionable(f)], "risk_level"
        ),
        "distinct_recommendations": len({
            f.get("recommendation_id", f["finding_id"]) for f in findings if f["category"] == "Recommendation"
        }),
        "hosts_with_unhealthy_recommendations": len({
            f["resource_id"] for f in findings if f["category"] == "Recommendation" and _is_actionable(f)
        }),
        "unknown_or_partial_sources": sum(s["status"] != "complete" for s in sources),
        "qualification": (
            "Counts describe this snapshot only. Null means unavailable/partial, not zero. "
            "Empty successfully paginated Arc-matched findings are not proof of zero risk. "
            "Resource Graph is indexed, may lag and does not verify current MDE sensor health."
        ),
    }


def _actions(inventory, findings, sources, provenance):
    by_id = {r["resource_id"]: r for r in inventory}
    definitions = [
        (
            "investigate-alerts", "Immediate review", "Investigate active high-severity alerts",
            "Defender reports an active Critical/High alert. A security analyst must validate and respond.",
            {f["resource_id"] for f in findings if (
                f["category"] == "Alert" and f["severity"] in ("Critical", "High")
                and f["status"].casefold() in ("active", "new", "inprogress")
            )}, ["defender_alerts"],
        ),
        (
            "restore-arc", "High priority", "Restore Arc connectivity before trusting freshness",
            "Disconnected/Expired Arc hosts create a visibility blind spot; installation alone is insufficient.",
            {r["resource_id"] for r in inventory if r["connectivity"] in ("Expired", "Disconnected")},
            ["arc_inventory"],
        ),
        (
            "review-mde", "High priority", "Repair MDE onboarding and verify the sensor",
            "Missing/failed extensions or independently unhealthy sensors require owner investigation.",
            {r["resource_id"] for r in inventory if (
                r["mde_extension"] in ("Failed", "Missing") or r["sensor_health"] == "Unhealthy"
            )}, ["arc_extensions", "mde_sensor_health"],
        ),
        (
            "review-findings", "High priority", "Review recommendations with native High/Critical risk",
            "Use Defender risk.level and owners; technical severity and CVSS are separate, not substituted.",
            {f["resource_id"] for f in findings if (
                f["category"] != "Alert" and f.get("risk_level") in ("Critical", "High")
                and f["status"].casefold() == "unhealthy"
            )}, ["defender_recommendations", "defender_vulnerabilities"],
        ),
        (
            "review-plan", "Verify coverage", "Confirm the effective protection baseline",
            "Free/unknown plans are coverage gaps; P1 versus P2 is an explicit licensing decision.",
            {r["resource_id"] for r in inventory if r["servers_plan"] != "P2"
             and r.get("resource_type", "microsoft.hybridcompute/machines") in (
                 "microsoft.hybridcompute/machines", "microsoft.compute/virtualmachines",
                 "microsoft.compute/virtualmachinescalesets",
             )},
            ["effective_servers_plan"],
        ),
        (
            "verify-health", "Verify coverage", "Obtain separate, current MDE sensor-health evidence",
            "ARM provisioning and WDATP integration do not prove that an endpoint sensor is healthy.",
            {r["resource_id"] for r in inventory if r["sensor_health"] == "Unknown"},
            ["mde_sensor_health"],
        ),
        (
            "review-remaining-findings", "Verify coverage", "Validate remaining indexed security findings",
            "Lower/unknown-severity unhealthy findings still need owner review; old evaluations may need revalidation.",
            {f["resource_id"] for f in findings if (
                f["category"] != "Alert" and f.get("risk_level") not in ("Critical", "High")
                and f["status"].casefold() == "unhealthy"
            )}, ["defender_recommendations", "defender_vulnerabilities"],
        ),
    ]
    result = []
    for action_id, priority, title, reason, resource_ids, source_names in definitions:
        if not resource_ids:
            continue
        names = sorted(by_id[rid]["server_name"] for rid in resource_ids)
        result.append({
            "action_id": action_id, "priority": priority, "title": title, "reason": reason,
            "affected_resources": len(resource_ids),
            "affected_servers": sum(
                by_id[rid].get("resource_type", "microsoft.hybridcompute/machines") in (
                    "microsoft.hybridcompute/machines", "microsoft.compute/virtualmachines",
                    "microsoft.compute/virtualmachinescalesets",
                ) for rid in resource_ids
            ),
            "server_sample": names[:5],
            "sample_returned": min(len(names), 5), "sample_has_more": len(names) > 5,
            "sources": source_names, "provenance": provenance,
        })
    # Unconfigured sensor telemetry already has its own verification action.
    unavailable = [
        s["name"] for s in sources if s["status"] != "complete" and s["name"] != "mde_sensor_health"
    ]
    if unavailable and inventory:
        result.append({
            "action_id": "restore-sources", "priority": "Verify coverage",
            "title": "Resolve unavailable or partial evidence sources",
            "reason": "Missing evidence is Unknown, not zero findings. Review source errors with an authorized operator.",
            "affected_resources": len(inventory),
            "affected_servers": sum(r.get("resource_type", "microsoft.hybridcompute/machines") in (
                "microsoft.hybridcompute/machines", "microsoft.compute/virtualmachines",
                "microsoft.compute/virtualmachinescalesets",
            ) for r in inventory), "server_sample": [],
            "sample_returned": 0, "sample_has_more": bool(inventory),
            "sources": unavailable, "provenance": provenance,
        })
    return result


def _review_actions(snapshot, inventory, findings):
    base = _actions(inventory, findings, snapshot["sources"], snapshot["provenance"])
    ids = {r["resource_id"] for r in inventory}
    paths = [p for p in snapshot["attack_paths"] if (
        p["risk_level"] in ("Critical", "High") and set(p.get("resource_ids", p["arc_resource_ids"])) & ids
    )]
    higher = []
    if paths:
        path_resources = {rid for p in paths for rid in p.get("resource_ids", p["arc_resource_ids"])}
        demo = snapshot["provenance"] == "SIMULATED"
        higher.append({
            "action_id": "review-demo-chains" if demo else "review-attack-paths",
            "priority": "High priority",
            "title": "Review illustrative SIMULATED chains" if demo else "Review observed High/Critical attack paths first",
            "reason": (
                "SIMULATED teaching chains only: examine exposure/trust and illustrative proposed breaks."
                if demo else
                "Defender reports High/Critical native paths. Review the actual entry/target, risk factors, "
                "linked assessments and source-recommended breaks before changes."
            ),
            "affected_resources": len(path_resources), "affected_servers": sum(
                r["resource_id"] in path_resources and r.get("resource_type") in (
                    "microsoft.hybridcompute/machines", "microsoft.compute/virtualmachines",
                    "microsoft.compute/virtualmachinescalesets",
                ) for r in inventory
            ),
            "affected_paths": len(paths), "path_ids": [p["path_id"] for p in paths],
            "risk_factors": sorted({factor for p in paths for factor in p["risk_factors"]}),
            "source_recommended_breaks": sorted({p["remediation"] for p in paths if p["remediation"]}),
            "scope": "SIMULATED illustrative Arc" if demo else "Subscription context",
            "sources": ["attack_paths"], "provenance": snapshot["provenance"],
            "server_sample": [], "sample_returned": 0, "sample_has_more": bool(path_resources),
        })
    critical = [v for v in snapshot["vulnerabilities"] if (
        v["technical_severity"] == "Critical" and v["resource_id"] in ids
    )]
    if critical:
        resource_ids = {v["resource_id"] for v in critical}
        higher.append({
            "action_id": "review-critical-cves", "priority": "High priority",
            "title": "Review source Critical CVEs and patch evidence",
            "reason": (
                "Embedded source CVEs have Critical technical severity. Validate source fix status, affected "
                "software/KB evidence and change impact; do not relabel native recommendation risk as Critical."
            ),
            "affected_resources": len(resource_ids), "affected_servers": sum(
                r["resource_id"] in resource_ids and r.get("resource_type") in (
                    "microsoft.hybridcompute/machines", "microsoft.compute/virtualmachines",
                    "microsoft.compute/virtualmachinescalesets",
                ) for r in inventory
            ),
            "cve_occurrences": len(critical), "distinct_cve_ids": len({v["cve_id"] for v in critical}),
            "native_risk_counts": _counts(
                [f for f in findings if f["finding_id"] in {v["finding_id"] for v in critical}], "risk_level"
            ),
            "sources": ["defender_recommendations.additionalData.CvesDetails"],
            "provenance": snapshot["provenance"], "scope": "Resource-level source evidence",
            "server_sample": [], "sample_returned": 0, "sample_has_more": bool(resource_ids),
        })
    immediate = [a for a in base if a["action_id"] == "investigate-alerts"]
    remaining = [a for a in base if a["action_id"] != "investigate-alerts"]
    remaining.sort(key=lambda a: (
        {"review-findings": 0, "restore-arc": 1, "review-mde": 2}.get(a["action_id"], 3)
    ))
    return immediate + higher + remaining


def _matches(row, params):
    if params.get("resource_type") and row.get("resource_type", "") != params["resource_type"]:
        return False
    if params["provider"] != "all" and row["provider"] != params["provider"]:
        return False
    if params["environment"] != "all" and row["environment"] != params["environment"]:
        return False
    if params["connectivity"] != "all" and row["connectivity"] != params["connectivity"]:
        return False
    if params["resource_group"] and row["resource_group"].casefold() != params["resource_group"].casefold():
        return False
    if params["server_name"] and params["server_name"].casefold() not in row["server_name"].casefold():
        return False
    mde = params["mde"]
    if mde == "failed-extension" and row["mde_extension"] != "Failed":
        return False
    if mde == "missing-extension" and row["mde_extension"] != "Missing":
        return False
    if mde == "unverified" and row["sensor_health"] != "Unknown":
        return False
    if mde == "healthy" and row["sensor_health"] != "Healthy":
        return False
    if mde == "unhealthy" and row["sensor_health"] != "Unhealthy":
        return False
    return True


def _query(snapshot, params):
    inventory = [r for r in snapshot["inventory"] if _matches(r, params)]
    selected_ids = {r["resource_id"] for r in inventory}
    findings = [f for f in snapshot["findings"] if (
        f["resource_id"] in selected_ids
        and (params["severity"] == "all" or f["severity"] == params["severity"])
        and (params["risk"] == "all" or f["risk_level"] == params["risk"])
        and (params["status"] == "all" or f["status"] == params["status"])
    )]
    if any(params[key] != "all" for key in ("severity", "risk", "status")):
        finding_ids = {f["resource_id"] for f in findings}
        inventory = [r for r in inventory if r["resource_id"] in finding_ids]
    if params["view"] == "inventory":
        query_fields = (
            "provenance", "server_name", "resource_id", "resource_group", "provider", "environment", "resource_type",
            "connectivity", "mde_extension", "sensor_health",
            "servers_plan", "plan_inherited", "priority",
            "observed_findings", "highest_observed_severity",
        )
        items = [{key: row[key] for key in query_fields} for row in inventory]
    elif params["view"] == "findings":
        query_fields = (
            "provenance", "server_name", "resource_id", "finding_id", "category",
            "technical_severity", "risk_level", "status", "title", "source",
            "recommendation_category", "assessment_type",
        )
        items = [{key: row[key] for key in query_fields} for row in findings]
    elif params["view"] == "actions":
        items = [
            _compact_action(action)
            for action in _review_actions(snapshot, inventory, findings)
        ]
    else:
        items = _section_query(snapshot, params, inventory, findings)
    offset, limit = params["offset"], params["limit"]
    page_candidates = items[offset:offset + limit]
    response = _transport_envelope(snapshot)
    all_source_statuses = response["sources"]
    view_sources = {
        "attack_paths": ("attack_paths",),
        "controls": ("secure_score_controls", "subscription_secure_score"),
        "posture": ("subscription_secure_score", "secure_score_controls", "risk_secure_score",
                    "attack_paths", "subscription_plans"),
        "compliance": ("compliance_standards", "compliance_controls", "compliance_assessments"),
        "software": ("software_inventory",),
        "vulnerabilities": ("defender_recommendations", "defender_vulnerabilities"),
        "resource_details": ("resource_inventory", "defender_recommendations", "arc_inventory",
                             "compute_extensions", "arc_extensions", "aks_security_profiles",
                             "software_inventory", "mde_sensor_health"),
        "inventory": ("resource_inventory", "arc_inventory", "arc_extensions",
                      "compute_extensions", "mde_sensor_health"),
        "findings": ("defender_recommendations", "defender_vulnerabilities", "defender_alerts"),
        "actions": ("attack_paths", "defender_recommendations", "defender_alerts",
                    "arc_inventory", "arc_extensions", "compute_extensions", "mde_sensor_health"),
    }
    response["sources"] = {
        name: all_source_statuses[name] for name in view_sources[params["view"]] if name in all_source_statuses
    }
    response.update({
        "view": params["view"],
        "filters": {
            k: v for k, v in params.items()
            if k not in ("operation", "view", "limit", "offset") and v not in ("all", "")
        },
        "summary_scope": "unfiltered_snapshot",
        "matched_servers": sum(r.get("resource_type", "microsoft.hybridcompute/machines") in (
            "microsoft.hybridcompute/machines", "microsoft.compute/virtualmachines",
            "microsoft.compute/virtualmachinescalesets",
        ) for r in inventory),
        "matched_resources": len(inventory),
        "matched_by_provider": dict(sorted(Counter(row["provider"] for row in inventory).items())),
        "matched_status_counts": _counts(findings, "status"),
        "matched_unhealthy_native_risks": _counts(
            [f for f in findings if f["category"] == "Recommendation" and _is_actionable(f)], "risk_level"
        ),
        "sources_total": len(all_source_statuses), "sources_returned": len(response["sources"]),
        "sources_has_more": len(response["sources"]) < len(all_source_statuses),
        "result_scope": (
            "Resource-level evidence" if params["view"] in ("inventory", "findings", "resource_details", "actions", "vulnerabilities")
            else "Subscription context; explicit Arc association where present"
        ),
        "total_matched": len(items), "requested_limit": limit, "offset": offset,
        "returned": 0, "has_more": offset < len(items),
        "next_offset": offset if offset < len(items) else None,
        "transport_capped": False, "items": [],
    })
    _check_transport_budget(response)

    def update_page():
        returned = len(response["items"])
        more = offset + returned < len(items)
        response.update({
            "returned": returned, "has_more": more,
            "next_offset": offset + returned if more else None,
        })

    for item in page_candidates:
        response["items"].append(item)
        update_page()
        if _response_bytes(response) > TRANSPORT_BUDGET_BYTES:
            response["items"].pop()
            response["transport_capped"] = True
            update_page()
            break
    if page_candidates and not response["items"]:
        raise EvidenceError(
            "query_item_exceeds_budget",
            "One evidence row cannot fit the safe stdout budget. Generate a report and inspect its full JSON snapshot.",
            "response_transport",
        )
    return _check_transport_budget(response)


def _section_query(snapshot, params, inventory, findings):
    ids = {r["resource_id"] for r in inventory}
    view = params["view"]
    if view == "resource_details":
        return [{
            "provenance": snapshot["provenance"], "server_name": r["server_name"],
            "resource_id": r["resource_id"], "location": r.get("location", "Unknown"),
            "os": r["os"], "os_version": r.get("os_version", "Unknown"),
            "parent_resource_id": r.get("parent_resource_id", ""),
            "inventory_source": r.get("inventory_source", "SIMULATED"),
            "tags": r.get("tags", {}), "recommendation_status_counts": r["recommendation_status_counts"],
            "recommendation_risk_counts": r["recommendation_risk_counts"],
            "software_records": r.get("software_records", 0), "extensions": r.get("extensions", []),
            "fim_configuration": r.get("fim_configuration", "Not verified"),
            "embedded_cve_records": r.get("embedded_cve_records", 0),
            "aks_monitoring_configured": r.get("aks_defender_monitoring_enabled"),
        } for r in inventory]
    if view == "vulnerabilities":
        return [{
            k: f.get(k) for k in (
                "server_name", "cve_id", "technical_severity", "fix_status",
                "fixed_version", "software_name", "risk_level", "source", "provenance",
            )
        } for f in snapshot["vulnerabilities"] if (
            f["resource_id"] in ids
            and (params["severity"] == "all" or f["technical_severity"] == params["severity"])
            and (params["risk"] == "all" or f["risk_level"] == params["risk"])
        )]
    if view == "posture":
        return snapshot["posture"]["scores"] + [{
            "scope": "Subscription context", "section": "attack_paths",
            "paths": len(snapshot["attack_paths"]),
            "arc_related": sum(bool(p["arc_resource_ids"]) for p in snapshot["attack_paths"]),
            "provenance": snapshot["provenance"],
        }]
    if view == "controls":
        return [{
            k: row.get(k) for k in (
                "title", "current", "maximum", "potential_score_gain", "healthy",
                "unhealthy", "not_applicable", "scope", "provenance",
            )
        } for row in snapshot["posture"]["controls"]]
    if view == "compliance":
        return snapshot["compliance"]["standards"]
    constrained = any(params[k] not in ("all", "") for k in (
        "provider", "environment", "resource_group", "server_name", "connectivity", "mde", "resource_type",
    ))
    rows = snapshot["attack_paths"] if view == "attack_paths" else snapshot["software"]
    selected = []
    for row in rows:
        arc_ids = row.get("arc_resource_ids", [])
        if params["association"] == "arc" and not arc_ids:
            continue
        if params["association"] == "context" and arc_ids:
            continue
        resource_ids = row.get("resource_ids", arc_ids)
        if constrained and not (set(resource_ids) & ids):
            continue
        if view == "attack_paths":
            if params["risk"] != "all" and row["risk_level"] != params["risk"]:
                continue
            selected.append({
                "path_id": row["path_id"], "title": row["title"], "risk_level": row["risk_level"],
                "association": row["association"], "entry_point": row["entry_point"]["name"],
                "target": row["target"]["name"], "entities": len(row["entities"]),
                "edges": len(row["edges"]), "risk_factors": row["risk_factors"],
                "recommended_break": _text(row["remediation"], 200),
                "scope": row["scope"], "provenance": row["provenance"],
                "full_graph_in_snapshot": True,
                "nodes": [{
                    "name": node["name"], "type": node["type"], "resource_id": node["resource_id"],
                } for node in row["entities"]],
                "connections": [{
                    "from": next(node["name"] for node in row["entities"] if node["entity_id"] == edge["source"]),
                    "to": next(node["name"] for node in row["entities"] if node["entity_id"] == edge["target"]),
                    "label": edge["label"],
                } for edge in row["edges"]],
            })
        else:
            selected.append({k: row.get(k) for k in (
                "server_name", "software_name", "version", "vendor", "known_vulnerabilities",
                "end_of_support_status", "association", "scope", "provenance",
            )})
    return selected


def _csv_cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        text = "'" + text
    return text


def _csv_document(rows, fields):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(fields)
    for row in rows:
        writer.writerow([_csv_cell(row.get(field)) for field in fields])
    return output.getvalue()


INVENTORY_CSV_FIELDS = (
    "provenance", "reference_utc", "server_name", "resource_id", "resource_group",
    "provider", "provider_evidence", "environment", "os", "connectivity",
    "last_status_change_utc", "mde_extension", "extension_evidence", "sensor_health",
    "sensor_evidence", "servers_plan", "plan_inherited", "plan_source",
    "priority", "priority_reasons", "observed_findings", "highest_observed_severity",
    "location", "tags", "recommendation_status_counts", "recommendation_risk_counts",
    "extensions", "fim_configuration",
)
FINDING_CSV_FIELDS = (
    "provenance", "reference_utc", "server_name", "resource_id", "resource_group",
    "provider", "environment", "category", "severity", "technical_severity", "risk_level", "status", "title",
    "finding_id", "source", "evidence", "source_time_utc", "first_evaluation_utc",
    "recommendation_category", "remediation", "portal_url", "patch", "cve_details",
)


def _safe_json(value):
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    )


def _check_snapshot_expansion(data, strings):
    """Preflight all expanded nodes/cell work and UTF-16 string units without building rows."""
    def invalid(message):
        raise EvidenceError("invalid_encoding", message, "artifact_encoding")

    def add(total, child, copies=1):
        nodes = total[0] + child[0] * copies
        units = total[1] + child[1] * copies
        if nodes > MAX_DECODED_NODES or units > MAX_DECODED_STRING_UNITS:
            raise EvidenceError(
                "encoding_expansion_exceeded",
                "Snapshot exceeds the bounded decoded expansion budget; no evidence was truncated.",
                "artifact_encoding",
            )
        return nodes, units

    def string(index):
        if type(index) is not int or not 0 <= index < len(strings):
            invalid("Invalid snapshot string reference.")
        return strings[index]

    def units(value):
        return len(value.encode("utf-16-le", "surrogatepass")) // 2

    def node(value, depth=0):
        if depth > 100:
            invalid("Snapshot nesting exceeds the safety bound.")
        if value is None or type(value) in (bool, int):
            return 1, 0
        if type(value) is float:
            if not math.isfinite(value):
                invalid("Snapshot contains a non-finite number.")
            return 1, 0
        if not isinstance(value, list) or not value or type(value[0]) is not int:
            invalid("Invalid encoded snapshot node.")
        tag = value[0]
        if tag == 0 and len(value) == 2:
            return add((0, 0), (1, units(string(value[1]))))
        if tag == 4 and len(value) == 1:
            return None
        if tag == 5 and len(value) == 2 and isinstance(value[1], str):
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value[1]):
                invalid("Invalid encoded snapshot float.")
            if not math.isfinite(float(value[1])):
                invalid("Snapshot contains a non-finite number.")
            return 1, 0
        if tag == 1 and len(value) == 2 and isinstance(value[1], list) and len(value[1]) % 2 == 0:
            total, seen = (1, 0), set()
            for offset in range(0, len(value[1]), 2):
                key, child = string(value[1][offset]), node(value[1][offset + 1], depth + 1)
                if key in seen or child is None:
                    invalid("Encoded object has a duplicate key or missing-value marker.")
                seen.add(key)
                total = add(add(total, (1, units(key))), child)
            return total
        if tag == 2 and len(value) == 2 and isinstance(value[1], list):
            total = (1, 0)
            for encoded in value[1]:
                child = node(encoded, depth + 1)
                if child is None:
                    invalid("Encoded array contains a missing-value marker.")
                total = add(total, child)
            return total
        if tag == 3 and len(value) == 4:
            count, fields, columns = value[1:]
            if (
                type(count) is not int or not 0 <= count <= 9_007_199_254_740_991
                or not isinstance(fields, list) or not isinstance(columns, list) or len(fields) != len(columns)
            ):
                invalid("Invalid snapshot column table.")
            total = add((1, 0), (1 + len(fields), 0), count)
            keys = [string(index) for index in fields]
            if len(set(keys)) != len(keys):
                invalid("Snapshot table has duplicate keys.")
            for key, encoded in zip(keys, columns):
                child, present = column(encoded, count, depth + 1)
                total = add(add(total, child), (0, units(key)), present)
            return total
        invalid("Unknown encoded snapshot node tag or shape.")

    def column(value, count, depth):
        if not isinstance(value, list) or not value or type(value[0]) is not int:
            invalid("Invalid encoded snapshot column.")
        tag = value[0]
        if tag == 0 and len(value) == 2:
            child = node(value[1], depth)
            return (add((0, 0), child, count), count) if child is not None else ((0, 0), 0)
        if tag == 1 and len(value) == 2 and isinstance(value[1], list) and len(value[1]) == count:
            total, present = (0, 0), 0
            for encoded in value[1]:
                child = node(encoded, depth)
                if child is not None:
                    total, present = add(total, child), present + 1
            return total, present
        if tag == 2 and len(value) == 2 and isinstance(value[1], list):
            total, present, covered = (0, 0), 0, 0
            for run in value[1]:
                if (
                    not isinstance(run, list) or len(run) != 2 or type(run[0]) is not int
                    or not 1 <= run[0] <= count - covered
                ):
                    invalid("Invalid snapshot run length.")
                child = node(run[1], depth)
                if child is not None:
                    total, present = add(total, child, run[0]), present + run[0]
                covered += run[0]
            if covered != count:
                invalid("Snapshot runs do not cover the complete table.")
            return total, present
        if tag == 3 and len(value) == 3 and isinstance(value[2], list):
            default = node(value[1], depth)
            total, present, seen = (0, 0), 0, set()
            for pair in value[2]:
                if (
                    not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int
                    or not 0 <= pair[0] < count or pair[0] in seen
                ):
                    invalid("Invalid snapshot sparse position.")
                seen.add(pair[0])
                child = node(pair[1], depth)
                if child is not None:
                    total, present = add(total, child), present + 1
            if default is not None:
                total = add(total, default, count - len(seen))
                present += count - len(seen)
            return total, present
        invalid("Unknown encoded snapshot column tag or shape.")

    cost = node(data)
    if cost is None:
        invalid("Restored snapshot must be an object.")
    return add((0, 0), cost)


def _pack_snapshot(snapshot):
    """Lossless recursive key/string dictionary with exact constant/run/sparse columns."""
    strings, lookup = [], {}
    missing = object()

    def invalid(message):
        raise EvidenceError("invalid_encoding", message, "artifact_encoding")

    def intern(value):
        if value not in lookup:
            lookup[value] = len(strings)
            strings.append(value)
        return lookup[value]

    def encode(value, depth=0):
        if depth > 100:
            invalid("Snapshot nesting exceeds the safety bound.")
        if value is missing:
            return [4]
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                invalid("Snapshot contains a non-finite number.")
            return [5, repr(value)]
        if isinstance(value, str):
            return [0, intern(value)]
        if isinstance(value, dict):
            fields = []
            for key, child in value.items():
                if not isinstance(key, str):
                    invalid("Snapshot object keys must be strings.")
                fields.extend((intern(key), encode(child, depth + 1)))
            return [1, fields]
        if isinstance(value, list):
            if len(value) >= 4 and all(isinstance(row, dict) for row in value):
                fields = {key for row in value for key in row}
                if any(not isinstance(key, str) for key in fields):
                    invalid("Snapshot table keys must be strings.")
                fields = sorted(fields)
                return [3, len(value), [intern(key) for key in fields], [
                    column([row.get(key, missing) for row in value], depth + 1) for key in fields
                ]]
            return [2, [encode(child, depth + 1) for child in value]]
        invalid("Snapshot contains an unsupported JSON value.")

    def column(values, depth):
        encoded = [encode(value, depth) for value in values]
        fingerprints = [json.dumps(value, separators=(",", ":"), allow_nan=False) for value in encoded]
        if len(set(fingerprints)) == 1:
            return [0, encoded[0]]
        runs = []
        for index, value in enumerate(encoded):
            if index and fingerprints[index] == fingerprints[index - 1]:
                runs[-1][0] += 1
            else:
                runs.append([1, value])
        default = Counter(fingerprints).most_common(1)[0][0]
        first = fingerprints.index(default)
        sparse = [[index, value] for index, value in enumerate(encoded) if fingerprints[index] != default]
        return min(
            ([1, encoded], [2, runs], [3, encoded[first], sparse]),
            key=lambda value: len(json.dumps(value, separators=(",", ":"), allow_nan=False)),
        )

    if not isinstance(snapshot, dict) or any(key not in snapshot for key in ("provenance", "reference_utc", "summary")):
        invalid("Normalized snapshot metadata is missing.")
    encoded = encode(snapshot)
    _check_snapshot_expansion(encoded, strings)
    return {
        "schema_version": "2.2", "encoding": "dictionary-columns-v2",
        "provenance": snapshot["provenance"], "reference_utc": snapshot["reference_utc"],
        "summary": snapshot["summary"], "strings": strings, "data": encoded,
    }


def _unpack_snapshot(document):
    """Restore complete evidence from ordinary, historical v1 or current v2 JSON."""
    def invalid(message):
        raise EvidenceError("invalid_encoding", message, "artifact_encoding")

    if not isinstance(document, dict):
        invalid("Snapshot document must be an object.")
    if "encoding" not in document:
        return document
    if document["encoding"] not in ("dictionary-columns-v1", "dictionary-columns-v2"):
        invalid("Unsupported snapshot encoding.")
    strings = document.get("strings")
    if not isinstance(strings, list) or any(not isinstance(s, str) for s in strings) or "data" not in document:
        invalid("Invalid snapshot string dictionary or missing data.")
    missing = object()

    def string(index):
        if type(index) is not int or not 0 <= index < len(strings):
            invalid("Invalid snapshot string reference.")
        return strings[index]

    def legacy(value, depth=0):
        if depth > 100:
            invalid("Snapshot nesting exceeds the safety bound.")
        if isinstance(value, str) and value.startswith("~"):
            if value.startswith("~~"):
                return value[1:]
            if not re.fullmatch(r"~[0-9]+", value):
                invalid("Invalid compact string reference.")
            try:
                index = int(value[1:])
            except ValueError:
                invalid("Invalid compact string reference.")
            return string(index)
        if isinstance(value, dict):
            if set(value) == {"$s"}:
                return string(value["$s"])
            if set(value) == {"$table", "rows"}:
                columns, rows = value["$table"], value["rows"]
                if (
                    not isinstance(columns, list) or any(not isinstance(c, str) for c in columns)
                    or len(set(columns)) != len(columns) or not isinstance(rows, list)
                ):
                    invalid("Invalid snapshot column table.")
                result = []
                for row in rows:
                    if not isinstance(row, list) or len(row) != len(columns):
                        invalid("Snapshot row/column counts differ.")
                    result.append({
                        key: legacy(cell, depth + 1) for key, cell in zip(columns, row)
                        if not (isinstance(cell, dict) and set(cell) == {"$missing"} and cell["$missing"] is True)
                    })
                return result
            if any(key in value for key in ("$s", "$table", "$missing")):
                invalid("Invalid reserved v1 codec marker.")
            return {key: legacy(child, depth + 1) for key, child in value.items()}
        if isinstance(value, list):
            return [legacy(child, depth + 1) for child in value]
        return value

    def decode(value, depth=0):
        if depth > 100:
            invalid("Snapshot nesting exceeds the safety bound.")
        if value is None or type(value) in (bool, int):
            return value
        if type(value) is float:
            if not math.isfinite(value):
                invalid("Snapshot contains a non-finite number.")
            return value
        if not isinstance(value, list) or not value or type(value[0]) is not int:
            invalid("Invalid encoded snapshot node.")
        tag = value[0]
        if tag == 0 and len(value) == 2:
            return string(value[1])
        if tag == 4 and len(value) == 1:
            return missing
        if tag == 5 and len(value) == 2 and isinstance(value[1], str):
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value[1]):
                invalid("Invalid encoded snapshot float.")
            number = float(value[1])
            if not math.isfinite(number):
                invalid("Snapshot contains a non-finite number.")
            return number
        if tag == 1 and len(value) == 2 and isinstance(value[1], list) and len(value[1]) % 2 == 0:
            result = {}
            for offset in range(0, len(value[1]), 2):
                key, child = string(value[1][offset]), decode(value[1][offset + 1], depth + 1)
                if key in result or child is missing:
                    invalid("Encoded object has a duplicate key or missing-value marker.")
                result[key] = child
            return result
        if tag == 2 and len(value) == 2 and isinstance(value[1], list):
            result = [decode(child, depth + 1) for child in value[1]]
            if any(child is missing for child in result):
                invalid("Encoded array contains a missing-value marker.")
            return result
        if tag == 3 and len(value) == 4:
            count, fields, columns = value[1:]
            if (
                type(count) is not int or not 0 <= count <= 9_007_199_254_740_991
                or not isinstance(fields, list) or not isinstance(columns, list) or len(fields) != len(columns)
            ):
                invalid("Invalid snapshot column table.")
            keys = [string(index) for index in fields]
            if len(set(keys)) != len(keys):
                invalid("Snapshot table has duplicate keys.")
            rows = [{} for _ in range(count)]
            for key, encoded in zip(keys, columns):
                for row, child in zip(rows, decode_column(encoded, count, depth + 1)):
                    if child is not missing:
                        row[key] = child
            return rows
        invalid("Unknown encoded snapshot node tag or shape.")

    def decode_column(value, count, depth):
        if not isinstance(value, list) or not value or type(value[0]) is not int:
            invalid("Invalid encoded snapshot column.")
        tag = value[0]
        if tag == 0 and len(value) == 2:
            return [decode(value[1], depth) for _ in range(count)]
        if tag == 1 and len(value) == 2 and isinstance(value[1], list) and len(value[1]) == count:
            return [decode(child, depth) for child in value[1]]
        if tag == 2 and len(value) == 2 and isinstance(value[1], list):
            result = []
            for run in value[1]:
                if (
                    not isinstance(run, list) or len(run) != 2 or type(run[0]) is not int
                    or not 1 <= run[0] <= count - len(result)
                ):
                    invalid("Invalid snapshot run length.")
                result.extend(decode(run[1], depth) for _ in range(run[0]))
            if len(result) != count:
                invalid("Snapshot runs do not cover the complete table.")
            return result
        if tag == 3 and len(value) == 3 and isinstance(value[2], list):
            overrides = {}
            for pair in value[2]:
                if (
                    not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not int
                    or not 0 <= pair[0] < count or pair[0] in overrides
                ):
                    invalid("Invalid snapshot sparse position.")
                overrides[pair[0]] = pair[1]
            return [decode(overrides.get(index, value[1]), depth) for index in range(count)]
        invalid("Unknown encoded snapshot column tag or shape.")

    if document["encoding"] == "dictionary-columns-v2":
        _check_snapshot_expansion(document["data"], strings)
    restored = legacy(document["data"]) if document["encoding"] == "dictionary-columns-v1" else decode(document["data"])
    if not isinstance(restored, dict):
        invalid("Restored snapshot must be an object.")
    return restored


def _rich_sections(snapshot):
    esc = lambda value: html.escape(str(value) if value is not None else "Unknown", quote=True)
    table = lambda headers, rows: (
        '<div class="table-wrap" tabindex="0"><table><thead><tr>'
        + "".join('<th scope="col">' + esc(h) + "</th>" for h in headers)
        + "</tr></thead><tbody>" + "".join(
            "<tr>" + "".join("<td>" + esc(v) + "</td>" for v in row) + "</tr>" for row in rows
        ) + "</tbody></table></div>"
    )
    summary = snapshot["summary"]
    statuses = summary["recommendation_status_counts"]
    source_lookup = {s["name"]: s for s in snapshot["sources"]}

    def availability(name):
        return source_lookup.get(name, {}).get("status", "unavailable")

    simulated = snapshot["provenance"] == "SIMULATED"
    scores = snapshot["posture"]["scores"]
    score = next((s for s in scores if s.get("name") == "ascScore"), scores[0] if scores else {})
    percentage = score.get("percentage")
    score_label = f"{percentage * 100:.2f}%" if percentage is not None else "Unknown"
    context_label = "SIMULATED illustrative posture" if simulated else "Subscription posture"
    executive = [
        (context_label + (" · illustrative baseline ratio" if simulated else " · classic Secure Score"), score_label,
         "SIMULATED healthy baseline share, not native Defender Secure Score." if simulated
         else "Observed subscription context, not an Arc-only score."),
        ("Unhealthy recommendation records", statuses.get("Unhealthy", 0),
         f"{summary['distinct_recommendations']} distinct definitions; records are resource/recommendation pairs."),
        ("Attack paths · context / Arc-related",
         f"{summary['attack_paths_subscription_context']} / {summary['attack_paths_arc_related']}"
         if availability("attack_paths") == "complete" else "Unknown",
         "Observed graph association only. Illustrative synthetic chains are not customer topology."),
        ("Embedded CVE evidence", summary["embedded_cve_records"],
         f"{summary['distinct_embedded_cves']} distinct IDs; zero standalone subassessments is not zero CVEs."),
    ]
    html_parts = [
        '<nav class="section-nav" aria-label="Report sections">'
        + "".join('<a href="#' + anchor + '">' + label + "</a>" for anchor, label in (
            ("posture", "Posture"), ("attack-paths", "Attack paths"), ("resource-detail", "Resources"),
            ("recommendations", "Recommendations"), ("software", "Software / CVEs"),
            ("compliance", "Compliance"), ("source-coverage", "Sources"),
        )) + "</nav>",
        '<section id="posture"><h2>What needs attention</h2><dl class="metrics">'
        + "".join("<div><dt>" + esc(label) + "</dt><dd>" + esc(value)
                  + "</dd><p>" + esc(note) + "</p></div>" for label, value, note in executive) + "</dl>",
        "<p class=\"note\">Native Defender risk and technical severity are independent. "
        "Healthy / Unhealthy / NotApplicable statuses are retained; counts never combine them as active risk. "
        "Retrieval time is not evaluation freshness.</p>",
        "<p><strong>Recommendation statuses:</strong> " + esc(json.dumps(statuses, sort_keys=True)) + "</p>",
        "<h2>Secure Score controls · subscription context</h2>"
        + "<p class=\"note\">Potential gain is control max minus current, not the guaranteed gain from one host. "
        "Control counts span the subscription; score availability: " + esc(availability("subscription_secure_score"))
        + ".</p><div class=\"workspace\">"
        + table(
            ("Control", "Current / max", "Potential gain", "Healthy", "Unhealthy", "Not applicable"),
            [(c["title"], f"{c['current']} / {c['maximum']}", c["potential_score_gain"],
              c["healthy"], c["unhealthy"], c["not_applicable"])
             for c in snapshot["posture"]["controls"]],
        ) + '</div><button type="button" data-export-section="controls">Export controls CSV</button></section>',
    ]
    if snapshot["posture"]["risk_score_observations"]:
        html_parts.append(
            '<details><summary>Native risk-score observations (no invented percentage)</summary>'
            + table(("Category", "Native numerator", "Native denominator"), [
                (r["assessment_category"], r["native_numerator"], r["native_denominator"])
                for r in snapshot["posture"]["risk_score_observations"]
            ]) + "<p>These opaque native values are not converted into a percentage.</p></details>"
        )
    html_parts.append('<section id="attack-paths"><h2>'
                      + ("Illustrative simulated attack chains" if simulated else "Observed Defender attack paths")
                      + '</h2><p class="note">'
                      + ("Fictional Arc on-premises/GCP teaching chains, not Defender detections or customer topology."
                         if simulated else
                         "Actual fixed-subscription context, not Arc-only paths. An empty edge set is preserved; no hops are invented.")
                      + " Source: " + esc(availability("attack_paths")) + ".</p>")
    for path in snapshot["attack_paths"]:
        lookup = {node["entity_id"]: node for node in path["entities"]}
        nodes = "".join(
            '<div class="graph-node"><strong>' + esc(node["name"]) + "</strong><span>"
            + esc(node["type"]) + "</span></div>" for node in path["entities"]
        )
        edges = "".join(
            "<li>" + esc(lookup[edge["source"]]["name"]) + " &rarr; "
            + esc(lookup[edge["target"]]["name"]) + ": " + esc(edge["label"]) + "</li>"
            for edge in path["edges"]
        ) or "<li>No connections returned by this source; entry point and target may be the same entity.</li>"
        related = [r for r in snapshot["subscription_recommendations"] if r["finding_id"].casefold() in path["assessment_ids"]]
        html_parts.append(
            '<article class="path-panel"><h3>' + esc(path["title"]) + "</h3><p><strong>Native risk: "
            + esc(path["risk_level"]) + "</strong> · " + esc(path["association"]) + " · "
            + esc(path["scope"]) + "</p><p>Entry: " + esc(path["entry_point"]["name"])
            + " · Target: " + esc(path["target"]["name"]) + "</p>"
            + '<div class="graph-nodes" role="group" aria-label="Observed graph entities">' + nodes + "</div>"
            + '<details><summary>Connections, insights and recommended breaks</summary><ul>' + edges + "</ul>"
            + "<p>Risk factors: " + esc(", ".join(path["risk_factors"])) + "</p><p>"
            + esc(path["story"]) + "</p><p><strong>Break / review:</strong> " + esc(path["remediation"]) + "</p>"
            + table(("Insight", "Observed values"), [
                (i["title"], json.dumps(i["observations"], ensure_ascii=False)) for i in path["insights"]
            ])
            + "<p>Linked assessment IDs: " + str(len(path["assessment_ids"]))
            + "; details available: " + str(len(related)) + ".</p>"
            + table(("Linked recommendation", "Status", "Native risk", "Remediation"), [
                (r["title"], r["status"], r["risk_level"], r["remediation"]) for r in related
            ]) + "</details></article>"
        )
    if not snapshot["attack_paths"]:
        html_parts.append("<p>No paths returned. Unavailable is Unknown, not proof of no exploitable path.</p>")
    html_parts.append('<button type="button" data-export-section="attack_paths">Export attack paths CSV</button></section>')
    kinds = {}
    for row in snapshot["inventory"]:
        kind = row.get("resource_kind", "Arc servers")
        value = kinds.setdefault(kind, {"resources": 0, "unhealthy": 0, "high": 0})
        value["resources"] += 1
        value["unhealthy"] += row["recommendation_status_counts"].get("Unhealthy", 0) > 0
        value["high"] += sum(row["recommendation_risk_counts"].get(k, 0) for k in ("High", "Critical"))
    html_parts.append(
        '<section id="resource-detail"><h2>Resource posture by service</h2><div class="workspace">'
        + table(("Service group", "Inventory resources", "Resources with unhealthy recommendations", "High/Critical native-risk records"), [
            (k, v["resources"], v["unhealthy"], v["high"]) for k, v in sorted(kinds.items())
        ]) + "</div><p class=\"note\">ARM inventory and Defender indexed-only dependent assets are labeled separately. "
        "No assessment is not a healthy-resource verdict. Select a resource to inspect ownership, recommendations, patches and software.</p>"
        + '<label for="detail-resource">Resource details</label><select id="detail-resource">'
        + "".join('<option value="' + esc(r["resource_id"]) + '">' + esc(r["server_name"])
                  + " · " + esc(r.get("resource_kind", "Arc servers")) + "</option>" for r in snapshot["inventory"])
        + '</select><div id="detail-content" class="resource-panel" aria-live="polite"></div></section>'
    )
    grouped = snapshot["recommendation_groups"]
    html_parts.append(
        '<section id="recommendations"><h2>Recommendations grouped by native risk and status</h2>'
        '<p class="note">Distinct definitions and affected resources are not the same as finding records. '
        'Use filters below or a resource selector for host-specific remediation; native risk never falls back to technical severity.</p>'
        '<div class="workspace"><div class="table-wrap" tabindex="0"><table id="groups-table"><thead><tr>'
        + "".join('<th scope="col">' + esc(h) + "</th>" for h in (
            "Recommendation / remediation", "Native risk", "Technical severity", "Status", "Records", "Resources",
        ))         + "</tr></thead><tbody></tbody></table></div></div>"
        + '<p id="groups-count" class="note" aria-live="polite"></p>'
        + '<button id="groups-more" type="button">Show more grouped recommendations</button>'
        + '<button type="button" data-export-section="recommendation_groups">Export grouped recommendations CSV</button></section>'
    )
    html_parts.append(
        '<section id="software"><h2>Software and embedded vulnerability evidence</h2>'
        + "<p class=\"note\">Software source: " + esc(availability("software_inventory"))
        + ". Inventory rows are observations, not a complete installed-software audit of hosts with no rows. "
        "Embedded CvesDetails are kept separately from standalone subassessments.</p><div class=\"workspace\">"
        + table(("Resource", "Software", "Version", "Vendor", "Known vulnerabilities", "Association"), [
            (s["server_name"], s["software_name"], s["version"], s["vendor"], s["known_vulnerabilities"], s["association"])
            for s in snapshot["software"]
        ]) + '</div><button type="button" data-export-section="software">Export software CSV</button>'
        + '<button type="button" data-export-section="vulnerabilities">Export source CVE evidence CSV</button>'
        + "<details><summary>Embedded vulnerability counts and provenance</summary><p>"
        + esc(json.dumps(_counts(snapshot["vulnerabilities"], "technical_severity")))
        + "</p><p>Occurrences: " + str(len(snapshot["vulnerabilities"])) + "; distinct IDs: "
        + str(summary["distinct_embedded_cves"])
        + ". Real CVEs only when returned by the live source; simulation uses DEMO-VA IDs.</p></details></section>"
    )
    html_parts.append(
        '<section id="compliance"><h2>Compliance observations, not certification</h2>'
        + '<p class="note">Passed, failed, skipped and unsupported controls remain separate. Scope is subscription; '
        "no automatic ENS/GDPR certification is claimed.</p><div class=\"workspace\">"
        + table(("Standard", "State", "Passed", "Failed", "Skipped", "Unsupported"), [
            (r["name"], r["state"], r.get("passedControls"), r.get("failedControls"),
             r.get("skippedControls"), r.get("unsupportedControls"))
            for r in snapshot["compliance"]["standards"]
        ]) + "</div><details><summary>Observed compliance controls and assessments</summary>"
        + table(("Control", "State", "Description", "Passed / failed / skipped assessments"), [
            (r["name"], r["state"], r.get("description", ""),
             f"{r.get('passedAssessments')} / {r.get('failedAssessments')} / {r.get('skippedAssessments')}")
            for r in snapshot["compliance"]["controls"]
        ]) + "<p>Assessment records: " + str(len(snapshot["compliance"]["assessments"])) + ".</p></details>"
        + '<button type="button" data-export-section="compliance">Export compliance controls CSV</button></section>'
        + "<h2>Observed protection plans</h2><p class=\"note\">Configured paid plans do not prove runtime health or "
        "all feature coverage. ACA source recommendations do not prove Defender for Containers runtime protection.</p>"
        + table(("Plan", "Tier", "Subplan", "Source coverage"), [
            (r["name"], r["pricing_tier"], r["sub_plan"], r["coverage"]) for r in snapshot["plans"]
        ])
    )
    return "".join(html_parts)


def _render_html(snapshot):
    escape = lambda value: html.escape("" if value is None else str(value), quote=True)
    simulated = snapshot["provenance"] == "SIMULATED"
    title = "SIMULATED hybrid posture" if simulated else "Defender for Cloud posture"
    subtitle = (
        "Mercadona-inspired on-premises / GCP demo. Synthetic assumptions, never customer measurements."
        if simulated else "Read-only security evidence across the configured lab's Azure services and dependent assessed assets."
    )
    notice = (
        "SIMULATED DEMO · 200 fictional servers · no Azure calls, tokens or customer measurements"
        if simulated else "LIVE SUBSCRIPTION SNAPSHOT · native risk is separate from severity · indexed evidence can lag"
    )
    source_rows = []
    for source in snapshot["sources"]:
        tone = "green" if source["status"] == "complete" else "amber"
        errors = "; ".join(e["message"] for e in source.get("errors", []))
        source_rows.append(
            "<tr><td>" + escape(source["name"]) + "</td><td><span class=\"badge " + tone + "\">"
            + escape(source["status"]) + "</span></td><td>"
            + escape(source["records"] if source.get("records") is not None else "Unknown")
            + "</td><td>" + escape(source["note"]) + (" " + escape(errors) if errors else "")
            + "</td></tr>"
        )
    action_rows = "".join(
        "<li><strong>" + escape(action["title"]) + "</strong><p>" + escape(action["reason"])
        + " Affected resources: " + str(action["affected_resources"]) + ".</p></li>"
        for action in snapshot["actions"][:3]
    ) or "<li>No action derived from the collected evidence; this is not zero-risk assurance.</li>"
    capabilities = "".join(
        "<tr><th scope=\"row\">" + escape(item["feature"]) + "</th><td>" + escape(item["scope"])
        + "</td><td>" + escape(item["caveat"]) + "</td></tr>" for item in CAPABILITY_MATRIX
    )
    summary = snapshot["summary"]
    metric_definitions = [
        ("Arc demo servers" if simulated else "Resources in evidence", len(snapshot["inventory"]),
         "ARM inventory / indexed-only assets are distinguished; no unverified portal parity"),
        ("Connected" if simulated else "Arc connected", summary["connected"],
         "Arc connectivity only; not reachability of the whole compute estate"),
        ("MDE extension succeeded", summary["mde_extension_succeeded"],
         "Observed Arc/Compute provisioning, not independently verified sensor health"),
        ("Sensor verified healthy", summary["sensor_verified_healthy"], "Unknown is not healthy"),
        ("Effective Servers P2" if simulated else "Arc effective Servers P2", summary["servers_p2"],
         "Per-Arc pricing reads only; broader subscription plans are separate, not health proof"),
    ]
    metrics = "".join(
        "<div><dt>" + escape(label) + "</dt><dd>" + str(count) + "</dd><p>" + escape(note) + "</p></div>"
        for label, count, note in metric_definitions
    )
    replacements = {
        "TITLE": escape(title), "SUBTITLE": escape(subtitle), "NOTICE": escape(notice),
        "PROVENANCE": escape(snapshot["provenance"]), "TIME": escape(snapshot["reference_utc"]),
        "SCOPE": escape(snapshot["scope"]["description"]), "COVERAGE": escape(snapshot["coverage"]["status"]),
        "LOGO": (
            '<img class="brand-logo" src="data:image/png;base64,' + LOGO_BASE64
            + '" alt="Mercadona" width="520" height="84">' if simulated
            else '<div class="neutral-brand">Security evidence<br><span>Defender for Cloud + SRE Agent</span></div>'
        ),
        "BODY_CLASS": "" if simulated else "live",
        "EXPANDED": _rich_sections(snapshot),
        "METRICS": metrics, "ACTIONS": action_rows, "INVENTORY": "",
        "FINDINGS": "", "SOURCES": "".join(source_rows), "CAPABILITIES": capabilities,
        "DATA": _safe_json(_pack_snapshot(snapshot)),
        "MAX_DECODED_NODES": str(MAX_DECODED_NODES),
        "MAX_DECODED_STRING_UNITS": str(MAX_DECODED_STRING_UNITS),
        "UNKNOWN_SOURCES": str(summary["unknown_or_partial_sources"]),
        "QUALIFICATION": escape(summary["qualification"]), "REFERENCE": DEFENDER_REFERENCE,
    }
    document = r"""<!doctype html>
<html lang="en">
<!-- THESIS: Make protection gaps and missing evidence actionable without inventing risk.
OWN-WORLD: Approved Mercadona forest/emerald header, serif headline, white logo plaque.
STORY: Check provenance, inspect source coverage, prioritize owners, filter and export evidence.
FIRST VIEWPORT: Left headline, top-right logo and coverage signal, evidence counts below.
FORM: Established credential-audit identity extended into a read-only operational evidence ledger. -->
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; connect-src 'none'">
<title>@@TITLE@@</title>
<style>
:root { --ink:#243c30; --muted:#52685a; --line:#d6e2d9; --paper:#f3f7f4; --panel:#fff;
 --forest:#0a3022; --emerald:#176347; --red:#a71e16; --red-soft:#fff0ed;
 --amber:#885000; --amber-soft:#fff5df; --green:#17633f; --green-soft:#e8f6ee; }
* {box-sizing:border-box} body {margin:0;background:var(--paper);color:var(--ink);
 font:15px/1.5 "Aptos","Segoe UI",sans-serif} button,input,select {font:inherit}
.shell {max-width:1600px;margin:auto;padding:28px}
.hero {position:relative;overflow:hidden;padding:30px 32px;border-radius:22px;color:#f5fff8;
 background:linear-gradient(120deg,#0a3022 0%,#0c4e33 55%,#176347 100%);
 box-shadow:0 18px 38px rgba(0,0,0,.14)}
.hero::after {content:"";position:absolute;width:480px;height:480px;right:-120px;top:-280px;
 border:1px solid rgba(223,255,233,.16);border-radius:50%;pointer-events:none}
.hero-grid {position:relative;z-index:1;display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:28px}
h1 {margin:6px 0 14px;font:700 clamp(34px,4.4vw,56px)/1.05 "Palatino Linotype",Georgia,serif;
 letter-spacing:-.03em;text-wrap:balance}
.subtitle {max-width:65ch;color:#e3f2e8;margin:0}
.hero-side {display:flex;flex-direction:column;gap:14px}
.brand-logo {width:268px;max-width:100%;height:auto;padding:12px 16px;border-radius:12px;background:white;
 box-shadow:0 8px 18px rgba(0,0,0,.1)}
.signal {padding:16px 18px;border:1px solid #aacbb7;border-radius:14px;background:rgba(3,29,17,.32)}
.signal strong {display:block;font:700 26px/1.15 "Palatino Linotype",Georgia,serif;color:#ffe5d9}
.signal p {margin:8px 0 0;color:#e1eee5;font-size:13px}
.context {position:relative;z-index:1;display:flex;flex-wrap:wrap;gap:8px 20px;margin-top:22px;color:#d9ecdf}
.provenance {padding:14px 0;font-weight:700;color:var(--forest);border-bottom:1px solid var(--line)}
.metrics {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:20px;margin:24px 0}
.metrics dt {font-size:13px;font-weight:700;color:var(--muted)}
.metrics dd {margin:6px 0;font:700 40px/1.1 "Palatino Linotype",Georgia,serif}
.metrics p {font-size:12px;color:var(--muted);margin:0}
h2 {font:700 27px/1.2 "Palatino Linotype",Georgia,serif;letter-spacing:-.02em;margin:36px 0 12px}
p {max-width:75ch} .note {color:var(--muted);font-size:13px}
.actions {padding:0;list-style:none;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}
.actions li {padding:16px 0;border-top:2px solid var(--amber)}
.actions p {margin:8px 0;font-size:13px;color:var(--muted)}
.workspace {border:1px solid var(--line);border-radius:14px;background:var(--panel);overflow:hidden}
.filters {display:grid;grid-template-columns:1.6fr repeat(4,1fr);gap:12px;padding:18px;background:#f8fbf9}
label {display:block;font-size:13px;font-weight:700;margin-bottom:6px;color:var(--muted)}
input,select {width:100%;min-height:44px;padding:8px 10px;border:1px solid #b3c8bb;border-radius:7px;
 background:white;color:var(--ink)} input::placeholder {color:#586b60;opacity:1}
button,.download {min-height:44px;padding:9px 14px;border:1px solid var(--emerald);border-radius:7px;
 background:var(--forest);color:white;font-weight:600;cursor:pointer;text-decoration:none}
button:hover,.download:hover {background:var(--emerald)}
button.secondary {background:white;color:var(--forest)}
:focus-visible {outline:3px solid #9b5900;outline-offset:3px}
.toolbar {display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:14px 18px}
.toolbar output {flex:1 1 220px;font-size:13px;color:var(--muted)}
.table-wrap {overflow:auto;border-top:1px solid var(--line)}
table {width:100%;border-collapse:collapse;min-width:1000px}
th,td {text-align:left;padding:13px 15px;border-bottom:1px solid var(--line);vertical-align:top;font-size:13px}
th {background:#f2f7f3;color:var(--muted);font-weight:700}
th button {background:transparent;border:0;color:var(--forest);padding:0;min-height:32px;font-size:13px}
th button:hover {background:transparent;text-decoration:underline}
tbody tr:hover {background:#f5faf6} td:first-child {font-weight:600;overflow-wrap:anywhere}
.badge {display:inline-block;border-radius:5px;padding:4px 7px;font-weight:700;white-space:nowrap}
.red {background:var(--red-soft);color:var(--red)}
.amber {background:var(--amber-soft);color:var(--amber)}
.green {background:var(--green-soft);color:var(--green)}
details {max-width:42ch;margin-top:8px} summary {cursor:pointer;color:var(--emerald);font-weight:600}
details p,details dd {font-size:12px;margin:6px 0} details dt {font-weight:600;font-size:12px}
.identifier {font:12px/1.5 Consolas,monospace;overflow-wrap:anywhere}
.empty {padding:16px 18px;margin:0;color:var(--muted);font-size:13px}
.sources table,.capabilities table {min-width:650px}
footer {margin-top:30px;color:var(--muted);font-size:13px} a {color:var(--emerald)}
.section-nav {display:flex;flex-wrap:wrap;gap:10px 20px;margin:20px 0;padding:12px 0;border-bottom:1px solid var(--line)}
.section-nav a {font-weight:600;text-decoration:none;min-height:32px;display:flex;align-items:center}
.path-panel,.resource-panel {padding:20px;margin:16px 0;border:1px solid var(--line);border-radius:12px;background:white}
.path-panel,.resource-panel,.graph-node {overflow-wrap:anywhere}
.resource-panel dd {margin:4px 0 14px;font-size:13px}.resource-panel dt {font-weight:600}
h3 {font-size:18px;margin:0 0 10px}.graph-nodes {display:flex;flex-wrap:wrap;gap:12px}
.graph-node {padding:12px;border:1px solid var(--line);border-radius:8px;max-width:300px}
.graph-node span {display:block;color:var(--muted);overflow-wrap:anywhere}
.neutral-brand {padding:18px;border:1px solid #6c92c9;border-radius:12px;font-size:18px;font-weight:600}
.neutral-brand span {font-size:13px;color:#d3e3fc}
body.live {--forest:#13294b;--emerald:#174b91;--ink:#1d2e48;--muted:#53657c;--paper:#f3f6fa;--line:#d3deec}
.live .hero {background:linear-gradient(120deg,#10233f,#173f67 70%,#174b91)}
.live h1,.live h2,.live .metrics dd {font-family:"Aptos","Segoe UI",sans-serif}
@media(max-width:1100px) {.metrics {grid-template-columns:repeat(3,1fr)}
 .filters {grid-template-columns:repeat(2,minmax(0,1fr))} .actions {grid-template-columns:1fr}}
@media(max-width:680px) {.shell {padding:14px} .hero {padding:24px;border-radius:16px}
 .hero-grid {grid-template-columns:1fr;gap:18px} .hero-side {display:contents}
 .brand-logo {grid-row:1;justify-self:end;width:240px} .hero-copy {grid-row:2}
 .signal {grid-row:3} h1 {font-size:34px;margin-top:0} .metrics {grid-template-columns:repeat(2,1fr)}
 .filters {grid-template-columns:1fr} .toolbar button {width:100%}}
@media(prefers-reduced-motion:reduce) {* {scroll-behavior:auto!important}}
@media print {.shell {padding:0}.filters,.toolbar button,th button::after {display:none}
 .hero {box-shadow:none} .table-wrap {overflow:visible} table {min-width:0} details {display:block}}
</style></head>
<body class="@@BODY_CLASS@@"><main class="shell">
<header class="hero"><div class="hero-grid"><div class="hero-copy">
<h1>@@TITLE@@</h1><p class="subtitle">@@SUBTITLE@@</p></div><div class="hero-side">
@@LOGO@@
<aside class="signal"><strong>Coverage: @@COVERAGE@@</strong>
<p>@@UNKNOWN_SOURCES@@ source(s) unknown or partial. Verify gaps before claiming protection.</p></aside></div></div>
<div class="context"><span>@@PROVENANCE@@</span><span>Reference UTC: @@TIME@@</span><span>Read-only</span></div></header>
<p class="provenance">@@NOTICE@@</p><p class="note">@@SCOPE@@</p>
<dl class="metrics" aria-label="Evidence counts">@@METRICS@@</dl>
@@EXPANDED@@
<h2>Three actions to review first</h2><p class="note">Evidence-based ordering, not a fabricated risk score.</p>
<ol class="actions">@@ACTIONS@@</ol>
<h2>Resource evidence ledger</h2>
<p class="note">MDE installation and verified sensor health are separate columns. Expand Evidence for each server.</p>
<section class="workspace" aria-label="Filterable resource inventory">
<div class="filters">
<div><label for="search">Resource or resource group</label><input id="search" type="search" placeholder="Search resource / group"></div>
<div><label for="provider">Hosting provider</label><select id="provider"><option value="">All locations</option>
<option value="onprem">On-premises</option><option value="gcp">GCP</option><option value="azure">Azure</option>
<option value="aws">AWS</option><option value="unknown">Unverified location</option></select></div>
<div><label for="environment">Environment</label><select id="environment"><option value="">All environments</option>
<option>Production</option><option>Preproduction</option><option>Dev</option><option>DMZ</option>
<option>Backup</option><option>Unknown</option></select></div>
<div><label for="connectivity">Arc connectivity</label><select id="connectivity"><option value="">All states</option>
<option>Connected</option><option>Disconnected</option><option>Expired</option><option>Unknown</option></select></div>
<div><label for="mde">Endpoint evidence</label><select id="mde"><option value="">All evidence</option>
<option value="failed-extension">Failed MDE extension</option><option value="missing-extension">Missing MDE extension</option>
<option value="unverified">Sensor health unverified</option><option value="healthy">Sensor verified healthy</option>
<option value="unhealthy">Sensor unhealthy</option></select></div></div>
<div class="toolbar"><label for="resource-type">Exact resource type</label><select id="resource-type">
<option value="">All resource types</option></select></div>
<div class="toolbar"><output id="inventory-count" aria-live="polite"></output>
<button id="reset" class="secondary" type="button">Reset filters</button>
<button id="inventory-csv" type="button">Export filtered resource CSV</button>
<button id="snapshot-json" class="secondary" type="button">Export full snapshot JSON</button></div>
<div class="table-wrap" tabindex="0" role="region" aria-label="Server table, horizontally scrollable">
<table id="inventory-table"><caption class="note">@@PROVENANCE@@ resource inventory at @@TIME@@</caption>
<thead><tr><th scope="col"><button type="button" data-sort="0">Resource</button></th>
<th scope="col"><button type="button" data-sort="1">Service group</button></th>
<th scope="col"><button type="button" data-sort="2">Environment</button></th>
<th scope="col"><button type="button" data-sort="3">OS</button></th>
<th scope="col"><button type="button" data-sort="4">Arc state</button></th>
<th scope="col"><button type="button" data-sort="5">MDE extension</button></th>
<th scope="col"><button type="button" data-sort="6">Sensor health</button></th>
<th scope="col"><button type="button" data-sort="7">Servers plan</button></th>
<th scope="col">Priority / evidence</th></tr></thead><tbody>@@INVENTORY@@</tbody></table></div>
<p class="empty" id="inventory-empty" hidden>No resources match these filters. Reset filters to see the full scope.</p></section>
<details><summary>All resource-level finding records and exports (including healthy / not applicable)</summary>
<h2>Source-observed security findings</h2><p class="note">@@QUALIFICATION@@</p>
<section class="workspace" aria-label="Arc-matched security findings"><div class="toolbar">
<div><label for="severity">Finding severity</label><select id="severity"><option value="">All severities</option>
<option>Critical</option><option>High</option><option>Medium</option><option>Low</option>
<option>Informational</option><option>Unknown</option></select></div>
<div><label for="risk">Native risk</label><select id="risk"><option value="">All risks</option>
<option>Critical</option><option>High</option><option>Medium</option><option>Low</option>
<option>Not evaluated</option><option>Unknown</option></select></div>
<div><label for="finding-status">Status</label><select id="finding-status"><option value="">All statuses</option>
<option>Unhealthy</option><option>Healthy</option><option>NotApplicable</option><option>Active</option></select></div>
<output id="findings-count" aria-live="polite"></output>
<button id="findings-more" class="secondary" type="button">Show more finding records</button>
<button id="findings-csv" type="button">Export filtered findings CSV</button></div>
<div class="table-wrap" tabindex="0" role="region" aria-label="Findings table, horizontally scrollable">
<table id="findings-table"><caption class="note">@@PROVENANCE@@ findings joined to exact resource IDs</caption>
<thead><tr><th scope="col"><button type="button" data-sort="0">Server</button></th>
<th scope="col"><button type="button" data-sort="1">Category</button></th>
<th scope="col"><button type="button" data-sort="2">Native risk / technical severity / status</button></th>
<th scope="col">Finding / evidence</th><th scope="col">Source</th></tr></thead><tbody>@@FINDINGS@@</tbody></table></div>
<p class="empty" id="findings-empty" hidden>No Arc-matched findings returned for these filters.
Check source coverage below; empty results do not mean zero risk.</p></section></details>
<h2 id="source-coverage">Source coverage and limitations</h2><section class="workspace sources">
<div class="table-wrap" tabindex="0" role="region" aria-label="Source coverage, horizontally scrollable">
<table><caption class="note">@@PROVENANCE@@ evidence availability</caption><thead><tr>
<th scope="col">Source</th><th scope="col">Status</th><th scope="col">Records</th>
<th scope="col">Meaning / unavailable evidence</th></tr></thead><tbody>@@SOURCES@@</tbody></table></div></section>
<h2>Capability boundaries, not blanket promises</h2><section class="workspace capabilities">
<div class="table-wrap" tabindex="0" role="region" aria-label="Capability boundaries, horizontally scrollable">
<table><caption class="note">Validate deployment requirements and separate licences against current official documentation.</caption>
<thead><tr><th scope="col">Feature</th><th scope="col">Applicability</th><th scope="col">Boundary</th></tr></thead>
<tbody>@@CAPABILITIES@@</tbody></table></div></section>
<footer><p>@@PROVENANCE@@ · @@TIME@@ · No cloud changes, customer security certification, cost ROI or incident-loss claims.
Subscription Secure Score and graphs are not Arc-only metrics; compliance is not certification.</p>
<p><a href="@@REFERENCE@@" target="_blank" rel="noopener noreferrer">Microsoft Defender for Servers: current feature matrix</a></p></footer>
<noscript><p>JavaScript is disabled. Full snapshot tables remain readable; use the companion CSV/JSON files for export.</p></noscript>
</main><script type="application/json" id="report-data">@@DATA@@</script>
<script>
"use strict";
const documentData = JSON.parse(document.getElementById("report-data").textContent);
function unpackSnapshot(doc) {
  const fail = message => {throw new Error(message);};
  const maxNodes = @@MAX_DECODED_NODES@@, maxStringUnits = @@MAX_DECODED_STRING_UNITS@@;
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  if (!object(doc)) fail("Snapshot document must be an object");
  if (!Object.hasOwn(doc, "encoding")) return doc;
  if (!["dictionary-columns-v1","dictionary-columns-v2"].includes(doc.encoding)
      || !Array.isArray(doc.strings) || doc.strings.some(value => typeof value !== "string")
      || !Object.hasOwn(doc, "data")) fail("Unsupported snapshot encoding or incomplete dictionary/data");
  const string = index => {
    if (!Number.isSafeInteger(index) || index < 0 || index >= doc.strings.length)
      fail("Invalid evidence string reference");
    return doc.strings[index];
  };
  const missing = Symbol("missing");
  function legacy(value, depth=0) {
    if (depth > 100) fail("Snapshot nesting exceeds the safety bound");
    if (typeof value === "string" && value.startsWith("~")) {
      if (value.startsWith("~~")) return value.slice(1);
      if (!/^~[0-9]+$/u.test(value)) fail("Invalid compact string reference");
      return string(Number(value.slice(1)));
    }
    if (Array.isArray(value)) return value.map(child => legacy(child,depth+1));
    if (object(value)) {
      const keys = Object.keys(value);
      if (keys.length === 1 && Object.hasOwn(value,"$s")) return string(value.$s);
      if (keys.length === 2 && Object.hasOwn(value,"$table") && Object.hasOwn(value,"rows")) {
        if (!Array.isArray(value.$table) || value.$table.some(key => typeof key !== "string")
            || new Set(value.$table).size !== value.$table.length || !Array.isArray(value.rows))
          fail("Invalid evidence table");
        return value.rows.map(row => {
          if (!Array.isArray(row) || row.length !== value.$table.length) fail("Invalid evidence table row");
          return Object.fromEntries(value.$table.flatMap((key,index) => {
            const cell = row[index];
            return object(cell) && cell.$missing === true && Object.keys(cell).length === 1
              ? [] : [[key,legacy(cell,depth+1)]];
          }));
        });
      }
      if (["$s","$table","$missing"].some(key => Object.hasOwn(value,key))) fail("Invalid reserved v1 codec marker");
      return Object.fromEntries(Object.entries(value).map(([key,child]) => [key,legacy(child,depth+1)]));
    }
    return value;
  }
  function node(value, depth=0) {
    if (depth > 100) fail("Snapshot nesting exceeds the safety bound");
    if (value === null || typeof value === "boolean") return value;
    if (typeof value === "number") {
      if (!Number.isFinite(value)) fail("Non-finite snapshot number");
      return value;
    }
    if (!Array.isArray(value) || !Number.isInteger(value[0])) fail("Invalid encoded snapshot node");
    const tag = value[0];
    if (tag === 0 && value.length === 2) return string(value[1]);
    if (tag === 4 && value.length === 1) return missing;
    if (tag === 5 && value.length === 2 && typeof value[1] === "string") {
      if (!/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/u.test(value[1]))
        fail("Invalid encoded snapshot float");
      const number = Number(value[1]);
      if (!Number.isFinite(number)) fail("Non-finite snapshot number");
      return number;
    }
    if (tag === 1 && value.length === 2 && Array.isArray(value[1]) && value[1].length % 2 === 0) {
      const result = Object.create(null);
      for (let i=0; i<value[1].length; i+=2) {
        const key = string(value[1][i]), child = node(value[1][i+1],depth+1);
        if (Object.hasOwn(result,key) || child === missing) fail("Duplicate or missing object key");
        result[key] = child;
      }
      return result;
    }
    if (tag === 2 && value.length === 2 && Array.isArray(value[1])) {
      const result = value[1].map(child => node(child,depth+1));
      if (result.includes(missing)) fail("Missing marker in an array");
      return result;
    }
    if (tag === 3 && value.length === 4) {
      const [count,fields,columns] = value.slice(1);
      if (!Number.isSafeInteger(count) || count < 0 || !Array.isArray(fields)
          || !Array.isArray(columns) || fields.length !== columns.length) fail("Invalid evidence table");
      const keys = fields.map(string);
      if (new Set(keys).size !== keys.length) fail("Duplicate evidence table key");
      const rows = Array.from({length:count}, () => Object.create(null));
      columns.forEach((encoded,i) => column(encoded,count,depth+1).forEach((child,j) => {
        if (child !== missing) rows[j][keys[i]] = child;
      }));
      return rows;
    }
    fail("Unknown encoded snapshot node tag or shape");
  }
  function column(value, count, depth) {
    if (!Array.isArray(value) || !Number.isInteger(value[0])) fail("Invalid encoded snapshot column");
    const tag = value[0];
    if (tag === 0 && value.length === 2) return Array.from({length:count}, () => node(value[1],depth));
    if (tag === 1 && value.length === 2 && Array.isArray(value[1]) && value[1].length === count)
      return value[1].map(child => node(child,depth));
    if (tag === 2 && value.length === 2 && Array.isArray(value[1])) {
      const result = [];
      for (const run of value[1]) {
        if (!Array.isArray(run) || run.length !== 2 || !Number.isSafeInteger(run[0])
            || run[0] < 1 || run[0] > count-result.length) fail("Invalid evidence run length");
        for (let i=0; i<run[0]; i++) result.push(node(run[1],depth));
      }
      if (result.length !== count) fail("Incomplete evidence runs");
      return result;
    }
    if (tag === 3 && value.length === 3 && Array.isArray(value[2])) {
      const overrides = new Map();
      for (const pair of value[2]) {
        if (!Array.isArray(pair) || pair.length !== 2 || !Number.isSafeInteger(pair[0])
            || pair[0] < 0 || pair[0] >= count || overrides.has(pair[0])) fail("Invalid sparse evidence position");
        overrides.set(pair[0],pair[1]);
      }
      return Array.from({length:count}, (_,i) => node(overrides.has(i) ? overrides.get(i) : value[1],depth));
    }
    fail("Unknown encoded snapshot column tag or shape");
  }
  function addCost(total, child, copies=1) {
    const nodes = total[0]+child[0]*copies, units = total[1]+child[1]*copies;
    if (nodes > maxNodes || units > maxStringUnits) fail("Snapshot exceeds the bounded decoded expansion budget");
    return [nodes,units];
  }
  function measure(value, depth=0) {
    if (depth > 100) fail("Snapshot nesting exceeds the safety bound");
    if (value === null || typeof value === "boolean") return [1,0];
    if (typeof value === "number") {
      if (!Number.isFinite(value)) fail("Non-finite snapshot number");
      return [1,0];
    }
    if (!Array.isArray(value) || !Number.isInteger(value[0])) fail("Invalid encoded snapshot node");
    const tag = value[0];
    if (tag === 0 && value.length === 2) return addCost([0,0],[1,string(value[1]).length]);
    if (tag === 4 && value.length === 1) return null;
    if (tag === 5 && value.length === 2 && typeof value[1] === "string") {node(value,depth); return [1,0];}
    if (tag === 1 && value.length === 2 && Array.isArray(value[1]) && value[1].length % 2 === 0) {
      let total = [1,0]; const seen = new Set();
      for (let i=0; i<value[1].length; i+=2) {
        const key = string(value[1][i]), child = measure(value[1][i+1],depth+1);
        if (seen.has(key) || child === null) fail("Duplicate or missing object key");
        seen.add(key); total = addCost(addCost(total,[1,key.length]),child);
      }
      return total;
    }
    if (tag === 2 && value.length === 2 && Array.isArray(value[1])) {
      let total = [1,0];
      for (const encoded of value[1]) {
        const child = measure(encoded,depth+1);
        if (child === null) fail("Missing marker in an array");
        total = addCost(total,child);
      }
      return total;
    }
    if (tag === 3 && value.length === 4) {
      const [count,fields,columns] = value.slice(1);
      if (!Number.isSafeInteger(count) || count < 0 || !Array.isArray(fields)
          || !Array.isArray(columns) || fields.length !== columns.length) fail("Invalid evidence table");
      let total = addCost([1,0],[1+fields.length,0],count);
      const keys = fields.map(string);
      if (new Set(keys).size !== keys.length) fail("Duplicate evidence table key");
      columns.forEach((encoded,i) => {
        const [child,present] = measureColumn(encoded,count,depth+1);
        total = addCost(addCost(total,child),[0,keys[i].length],present);
      });
      return total;
    }
    fail("Unknown encoded snapshot node tag or shape");
  }
  function measureColumn(value, count, depth) {
    if (!Array.isArray(value) || !Number.isInteger(value[0])) fail("Invalid encoded snapshot column");
    const tag = value[0];
    if (tag === 0 && value.length === 2) {
      const child = measure(value[1],depth);
      return child === null ? [[0,0],0] : [addCost([0,0],child,count),count];
    }
    if (tag === 1 && value.length === 2 && Array.isArray(value[1]) && value[1].length === count) {
      let total = [0,0], present = 0;
      for (const encoded of value[1]) {
        const child = measure(encoded,depth);
        if (child !== null) {total = addCost(total,child); present++;}
      }
      return [total,present];
    }
    if (tag === 2 && value.length === 2 && Array.isArray(value[1])) {
      let total = [0,0], present = 0, covered = 0;
      for (const run of value[1]) {
        if (!Array.isArray(run) || run.length !== 2 || !Number.isSafeInteger(run[0])
            || run[0] < 1 || run[0] > count-covered) fail("Invalid evidence run length");
        const child = measure(run[1],depth);
        if (child !== null) {total = addCost(total,child,run[0]); present += run[0];}
        covered += run[0];
      }
      if (covered !== count) fail("Incomplete evidence runs");
      return [total,present];
    }
    if (tag === 3 && value.length === 3 && Array.isArray(value[2])) {
      const fallback = measure(value[1],depth), seen = new Set();
      let total = [0,0], present = 0;
      for (const pair of value[2]) {
        if (!Array.isArray(pair) || pair.length !== 2 || !Number.isSafeInteger(pair[0])
            || pair[0] < 0 || pair[0] >= count || seen.has(pair[0])) fail("Invalid sparse evidence position");
        seen.add(pair[0]);
        const child = measure(pair[1],depth);
        if (child !== null) {total = addCost(total,child); present++;}
      }
      if (fallback !== null) {total = addCost(total,fallback,count-seen.size); present += count-seen.size;}
      return [total,present];
    }
    fail("Unknown encoded snapshot column tag or shape");
  }
  if (doc.encoding === "dictionary-columns-v2") {
    const cost = measure(doc.data);
    if (cost === null) fail("Restored snapshot must be an object");
    addCost([0,0],cost);
  }
  const restored = doc.encoding === "dictionary-columns-v1" ? legacy(doc.data) : node(doc.data);
  if (!object(restored)) fail("Restored snapshot must be an object");
  return restored;
}
const snapshot = unpackSnapshot(documentData);
const servers = new Map(snapshot.inventory.map(row => [row.resource_id, row]));
let findingLimit = 50, groupLimit = 50, filteredFindings = [], filteredGroups = [];
const filterIds = ["search", "provider", "environment", "connectivity", "mde", "severity",
 "risk", "finding-status", "resource-type"];
function matches(row) {
  const search = document.getElementById("search").value.trim().toLowerCase();
  if (search && !(row.server_name + " " + row.resource_group).toLowerCase().includes(search)) return false;
  for (const field of ["provider", "environment", "connectivity"]) {
    const value = document.getElementById(field).value;
    if (value && row[field] !== value) return false;
  }
  const mde = document.getElementById("mde").value;
  const type = document.getElementById("resource-type").value;
  if (type && row.resource_type !== type) return false;
  if (mde === "failed-extension" && row.mde_extension !== "Failed") return false;
  if (mde === "missing-extension" && row.mde_extension !== "Missing") return false;
  if (mde === "unverified" && row.sensor_health !== "Unknown") return false;
  if (mde === "healthy" && row.sensor_health !== "Healthy") return false;
  if (mde === "unhealthy" && row.sensor_health !== "Unhealthy") return false;
  return true;
}
function applyFilters() {
  const selected = new Set(snapshot.inventory.filter(matches).map(row => row.resource_id));
  const severity = document.getElementById("severity").value;
  const risk = document.getElementById("risk").value;
  const status = document.getElementById("finding-status").value;
  let visibleServers = 0;
  const inventoryBody = document.querySelector("#inventory-table tbody");
  inventoryBody.replaceChildren();
  snapshot.inventory.filter(item => selected.has(item.resource_id)).forEach(item => {
    const row = document.createElement("tr"); row.dataset.id = item.resource_id;
    [item.server_name,item.resource_kind || "Arc servers",item.environment,item.os,
      item.connectivity,item.mde_extension,item.sensor_health,item.servers_plan,item.priority]
      .forEach(value => row.appendChild(textElement("td", value)));
    inventoryBody.appendChild(row); visibleServers++;
  });
  filteredFindings = snapshot.findings.filter(item => selected.has(item.resource_id)
    && (!severity || item.technical_severity === severity) && (!risk || item.risk_level === risk)
    && (!status || item.status === status));
  filteredGroups = snapshot.recommendation_groups.filter(group =>
    group.resource_ids.some(id => selected.has(id)) && (!risk || group.risk_level === risk)
    && (!status || group.status === status) && (!severity || group.technical_severity === severity));
  renderPagedTables();
  document.getElementById("inventory-count").textContent =
    visibleServers + " of " + snapshot.inventory.length + " resources · " + snapshot.provenance;
  document.getElementById("inventory-empty").hidden = visibleServers !== 0;
  document.getElementById("findings-empty").hidden = filteredFindings.length !== 0;
}
function csvCell(value) {
  let text = value == null ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
  if (/^[\s]*[=+\-@]/u.test(text) || /^[\t\r\n]/u.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}
function download(content, mime, filename) {
  const url = URL.createObjectURL(new Blob([content], {type:mime}));
  const link = document.createElement("a");
  link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function exportCsv(rows, fields, filename) {
  const lines = [fields.map(csvCell).join(",")];
  rows.forEach(row => lines.push(fields.map(field => csvCell(row[field])).join(",")));
  download("\ufeff" + lines.join("\r\n"), "text/csv;charset=utf-8", filename);
}
document.getElementById("inventory-csv").addEventListener("click", () => {
  const rows = Array.from(document.querySelectorAll("#inventory-table tbody tr"))
    .filter(row => !row.hidden).map(row => servers.get(row.dataset.id));
  exportCsv(rows, snapshot.inventory_csv_fields, snapshot.provenance + "-arc-servers-filtered.csv");
});
document.getElementById("findings-csv").addEventListener("click", () => {
  exportCsv(filteredFindings, snapshot.finding_csv_fields, snapshot.provenance + "-findings-filtered.csv");
});
document.getElementById("snapshot-json").addEventListener("click", () =>
  download(JSON.stringify(documentData), "application/json", snapshot.provenance + "-snapshot.json"));
const typeSelector = document.getElementById("resource-type");
Array.from(new Set(snapshot.inventory.map(r => r.resource_type || "microsoft.hybridcompute/machines")))
 .sort().forEach(value => {const option = document.createElement("option");
  option.value = value; option.textContent = value; typeSelector.appendChild(option);});
function textElement(tag, text) {
  const node = document.createElement(tag); node.textContent = String(text == null ? "Unknown" : text); return node;
}
function renderPagedTables() {
  const findingsBody = document.querySelector("#findings-table tbody");
  findingsBody.replaceChildren();
  filteredFindings.slice(0,findingLimit).forEach(finding => {
    const row = document.createElement("tr");
    [finding.server_name, finding.category,
      "Native: " + finding.risk_level + " · Technical: " + finding.technical_severity + " · " + finding.status,
      finding.title, finding.source].forEach(value => row.appendChild(textElement("td", value)));
    findingsBody.appendChild(row);
  });
  document.getElementById("findings-count").textContent =
    "Showing " + Math.min(findingLimit,filteredFindings.length) + " of " + filteredFindings.length
    + " matched findings (" + snapshot.findings.length + " total). CSV exports ALL matches.";
  document.getElementById("findings-more").hidden = findingLimit >= filteredFindings.length;
  const groupsBody = document.querySelector("#groups-table tbody");
  groupsBody.replaceChildren();
  filteredGroups.slice(0,groupLimit).forEach(group => {
    const row = document.createElement("tr"), cell = document.createElement("td");
    cell.appendChild(textElement("strong", group.title));
    const details = document.createElement("details"); details.appendChild(textElement("summary", "Remediation and resources"));
    details.appendChild(textElement("p", group.remediation));
    details.appendChild(textElement("p", group.server_names.join(", "))); cell.appendChild(details); row.appendChild(cell);
    [group.risk_level,group.technical_severity,group.status,group.records,group.affected_resources]
      .forEach(value => row.appendChild(textElement("td", value)));
    groupsBody.appendChild(row);
  });
  document.getElementById("groups-count").textContent =
    "Showing " + Math.min(groupLimit,filteredGroups.length) + " of " + filteredGroups.length
    + " matched groups. CSV exports ALL matches.";
  document.getElementById("groups-more").hidden = groupLimit >= filteredGroups.length;
}
document.getElementById("findings-more").addEventListener("click", () => {findingLimit += 50; renderPagedTables();});
document.getElementById("groups-more").addEventListener("click", () => {groupLimit += 50; renderPagedTables();});
function renderResource() {
  const root = document.getElementById("detail-content");
  root.replaceChildren();
  const resource = servers.get(document.getElementById("detail-resource").value);
  if (!resource) {root.appendChild(textElement("p", "No resource evidence available.")); return;}
  root.appendChild(textElement("h3", resource.server_name));
  root.appendChild(textElement("p", resource.resource_id));
  const facts = document.createElement("dl");
  const observations = {
    "Inventory source": resource.inventory_source || "SIMULATED fixture",
    "Resource type": resource.resource_type || "microsoft.hybridcompute/machines",
    "Azure location (not physical Arc hosting)": resource.location,
    "OS / version": resource.os + " / " + (resource.os_version || "Unknown"),
    "Ownership tags": JSON.stringify(resource.tags || {}),
    "Recommendation statuses": JSON.stringify(resource.recommendation_status_counts),
    "Unhealthy native risks": JSON.stringify(resource.recommendation_risk_counts),
    "MDE installation / sensor": resource.mde_extension + " / " + resource.sensor_health,
    "Extensions": JSON.stringify(resource.extensions || []),
    "FIM configuration": resource.fim_configuration || "Not verified",
    "AKS monitoring configured (not health)": resource.aks_defender_monitoring_enabled,
    "Software rows observed": resource.software_records,
    "Embedded CVE occurrences": resource.embedded_cve_records
  };
  Object.entries(observations).forEach(([key,value]) => {
    facts.appendChild(textElement("dt", key)); facts.appendChild(textElement("dd", value));
  });
  root.appendChild(facts);
  const findings = snapshot.findings.filter(f => f.resource_id === resource.resource_id);
  root.appendChild(textElement("p", findings.length + " finding records, all statuses. Showing first 30; complete evidence is exported."));
  const list = document.createElement("ul");
  findings.slice(0,30).forEach(finding => {
    const item = document.createElement("li");
    item.appendChild(textElement("strong", finding.title));
    item.appendChild(textElement("p", "Status: " + finding.status + " · Native risk: "
      + finding.risk_level + " · Technical severity: " + finding.technical_severity));
    item.appendChild(textElement("p", finding.remediation || "Remediation not supplied by this source."));
    if (finding.patch) item.appendChild(textElement("p", JSON.stringify(finding.patch)));
    if (finding.portal_url) {
      const link = textElement("a", "Review native recommendation");
      link.href = finding.portal_url; link.target = "_blank"; link.rel = "noopener noreferrer";
      item.appendChild(link);
    }
    list.appendChild(item);
  });
  root.appendChild(list);
  const exportButton = textElement("button", "Export all findings for this resource");
  exportButton.type = "button"; exportButton.addEventListener("click", () =>
    exportCsv(findings, snapshot.finding_csv_fields, snapshot.provenance + "-resource-findings.csv"));
  root.appendChild(exportButton);
  const cves = snapshot.vulnerabilities.filter(v => v.resource_id === resource.resource_id);
  const cveButton = textElement("button", "Export all embedded CVEs for this resource");
  cveButton.type = "button"; cveButton.addEventListener("click", () => exportCsv(cves,
    ["provenance","reference_utc","server_name","cve_id","technical_severity","fix_status","fixed_version","source"],
    snapshot.provenance + "-resource-cves.csv"));
  root.appendChild(cveButton);
}
document.getElementById("detail-resource").addEventListener("change", renderResource);
document.querySelectorAll("[data-export-section]").forEach(button => button.addEventListener("click", () => {
  const key = button.dataset.exportSection;
  let rows = key === "controls" ? snapshot.posture.controls
    : key === "compliance" ? snapshot.compliance.controls : snapshot[key];
  if (key === "recommendation_groups") {
    rows = filteredGroups;
  }
  const fields = rows.length ? Object.keys(rows[0]) : ["provenance","reference_utc"];
  exportCsv(rows, fields, snapshot.provenance + "-" + key + ".csv");
}));
document.getElementById("reset").addEventListener("click", () => {
  filterIds.forEach(id => {document.getElementById(id).value = "";});
  findingLimit = 50; groupLimit = 50; applyFilters();
});
filterIds.forEach(id => document.getElementById(id).addEventListener("input", applyFilters));
document.querySelectorAll("button[data-sort]").forEach(button => button.addEventListener("click", () => {
  const table = button.closest("table"), th = button.closest("th"), column = Number(button.dataset.sort);
  const ascending = th.getAttribute("aria-sort") !== "ascending";
  table.querySelectorAll("th").forEach(header => header.removeAttribute("aria-sort"));
  th.setAttribute("aria-sort", ascending ? "ascending" : "descending");
  if (table.id === "findings-table") {
    const field = ["server_name","category","risk_level","title","source"][column];
    filteredFindings.sort((a,b) => String(a[field]).localeCompare(String(b[field]),
      undefined, {numeric:true,sensitivity:"base"}) * (ascending ? 1 : -1));
    renderPagedTables(); return;
  }
  const rows = Array.from(table.tBodies[0].rows);
  rows.sort((a,b) => a.cells[column].textContent.localeCompare(b.cells[column].textContent,
    undefined, {numeric:true,sensitivity:"base"}) * (ascending ? 1 : -1));
  rows.forEach(row => table.tBodies[0].appendChild(row));
}));
applyFilters();
renderResource();
</script></body></html>"""
    return re.sub(r"@@([A-Z_]+)@@", lambda match: replacements[match.group(1)], document)


def _finish_snapshot(inventory, findings, sources, provenance, reference, scope, assumptions=None, context=None):
    context = context or {}
    for finding in findings:
        finding.setdefault("technical_severity", finding["severity"])
        finding.setdefault("risk_level", "Not evaluated")
        finding.setdefault("recommendation_id", finding["finding_id"].rsplit("/", 1)[-1])
        finding.setdefault("remediation", "")
        finding.setdefault("recommendation_category", finding["category"])
        finding.setdefault("assessment_type", "SIMULATED" if provenance == "SIMULATED" else "Unknown")
        finding.setdefault("cve_details", [])
        finding.setdefault("patch", {})
    _enrich_inventory(inventory, findings, provenance)
    partial = any(source["status"] != "complete" for source in sources)
    for row in inventory + findings:
        row["reference_utc"] = reference
        row["provenance"] = provenance
    snapshot = {
        "schema_version": "2.0", "status": "partial" if partial else "success",
        "provenance": provenance, "reference_utc": reference, "scope": scope,
        "coverage": {
            "status": "partial" if partial else "complete",
            "inventory_pagination_completed": True, "inventory_servers": len(inventory),
            "sensor_health_is_separate_from_extension": True,
            "scope_is_arc_only": provenance == "SIMULATED", "inventory_scope_is_arc_only": provenance == "SIMULATED",
            "subscription_secure_score_collected": bool(context.get("posture", {}).get("scores")),
            "context_metrics_are_not_arc_scores": True,
        },
        "summary": _summary(inventory, findings, sources),
        "sources": sources, "inventory": inventory, "findings": findings,
        "actions": _actions(inventory, findings, sources, provenance),
        "capability_matrix": CAPABILITY_MATRIX, "feature_reference": DEFENDER_REFERENCE,
        "inventory_csv_fields": list(INVENTORY_CSV_FIELDS),
        "finding_csv_fields": list(FINDING_CSV_FIELDS),
        "recommendation_groups": _group_recommendations(findings),
        "posture": context.get("posture", {"scores": [], "controls": [], "risk_score_observations": []}),
        "attack_paths": context.get("attack_paths", []),
        "software": context.get("software", []),
        "plans": context.get("plans", []),
        "compliance": context.get("compliance", {"standards": [], "controls": [], "assessments": []}),
        "subscription_recommendations": context.get("subscription_recommendations", []),
        "vulnerabilities": [],
    }
    for finding in findings:
        for cve in finding["cve_details"]:
            snapshot["vulnerabilities"].append({
                **cve, "finding_id": finding["finding_id"], "resource_id": finding["resource_id"],
                "server_name": finding["server_name"], "software_name": finding["patch"].get("software_name", ""),
                "risk_level": finding["risk_level"], "source": finding["source"] + ".additionalData.CvesDetails",
                "provenance": provenance, "reference_utc": reference,
            })
    for row in inventory:
        row["software_records"] = sum(row["resource_id"] == s["resource_id"] for s in snapshot["software"])
        row["attack_path_records"] = sum(
            row["resource_id"] in p.get("resource_ids", p["arc_resource_ids"]) for p in snapshot["attack_paths"]
        )
        row["embedded_cve_records"] = sum(v["resource_id"] == row["resource_id"] for v in snapshot["vulnerabilities"])
    snapshot["summary"].update({
        "embedded_cve_records": len(snapshot["vulnerabilities"]),
        "distinct_embedded_cves": len({v["cve_id"] for v in snapshot["vulnerabilities"]}),
        "distinct_resource_cve_pairs": len({(v["resource_id"], v["cve_id"]) for v in snapshot["vulnerabilities"]}),
        "embedded_cve_technical_severity_counts": _counts(snapshot["vulnerabilities"], "technical_severity"),
        "attack_paths_subscription_context": len(snapshot["attack_paths"]),
        "attack_paths_arc_related": sum(bool(p["arc_resource_ids"]) for p in snapshot["attack_paths"]),
        "software_records_subscription_context": len(snapshot["software"]),
        "software_records_arc_related": sum(bool(s["arc_resource_ids"]) for s in snapshot["software"]),
    })
    snapshot["actions"] = _review_actions(snapshot, inventory, findings)
    if assumptions is not None:
        snapshot["synthetic_assumptions"] = assumptions
    return snapshot


def _artifact_directory():
    try:
        root = Path.cwd().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EvidenceError(
            "unsafe_artifact_root", "Could not resolve the runtime working root.", "artifact_storage"
        ) from exc
    if root == Path(root.anchor) or not root.is_dir():
        raise EvidenceError(
            "unsafe_artifact_root", "Runtime cwd must be an existing non-filesystem-root directory.", "artifact_storage"
        )
    if OUTPUT_DIRECTORY != Path("arc-defender-reports"):
        raise EvidenceError(
            "unsafe_artifact_directory", "Only the fixed arc-defender-reports subdirectory is allowed.", "artifact_storage"
        )
    try:
        directory = (root / OUTPUT_DIRECTORY).resolve()
    except (OSError, RuntimeError) as exc:
        raise EvidenceError(
            "unsafe_artifact_directory", "Could not resolve the runtime-owned export directory.", "artifact_storage"
        ) from exc
    if directory == root or not directory.is_relative_to(root):
        raise EvidenceError(
            "unsafe_artifact_directory", "Resolved report directory escapes the runtime working root.", "artifact_storage"
        )
    return root, directory


def _write_report(snapshot):
    if not isinstance(LOGO_BASE64, str) or len(LOGO_BASE64) < 100:
        raise EvidenceError("asset_missing", "The approved embedded logo is missing.", "report_renderer")
    root, directory = _artifact_directory()
    prefix = (
        ("arc-demo-" if snapshot["provenance"] == "SIMULATED" else "defender-")
        + snapshot["reference_utc"].replace(":", "").replace("-", "") + "-" + uuid4().hex[:8]
    )
    paths = {
        "report_path": directory / (prefix + ".html"),
        "csv_path": directory / (prefix + "-servers.csv"),
        "findings_csv_path": directory / (prefix + "-findings.csv"),
        "snapshot_path": directory / (prefix + "-snapshot.json"),
    }
    snapshot_document = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(snapshot_document.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        snapshot_document = json.dumps(
            _pack_snapshot(snapshot), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    documents = {
        "report_path": _render_html(snapshot),
        "csv_path": _csv_document(snapshot["inventory"], INVENTORY_CSV_FIELDS),
        "findings_csv_path": _csv_document(snapshot["findings"], FINDING_CSV_FIELDS),
        "snapshot_path": snapshot_document,
    }
    for name in ("report_path", "snapshot_path"):
        if len(documents[name].encode("utf-8")) > MAX_ARTIFACT_BYTES:
            raise EvidenceError(
                "artifact_size_exceeded",
                "Complete evidence cannot fit the safe 4800000-byte plain HTML/JSON sharing limit; no data was truncated.",
                "artifact_storage",
            )
    written = []
    temporary_paths = []
    try:
        directory.mkdir(exist_ok=True)
        resolved = directory.resolve(strict=True)
        if resolved != directory or not resolved.is_relative_to(root):
            raise EvidenceError(
                "unsafe_artifact_directory", "Export directory changed scope after creation.", "artifact_storage"
            )
        for key, path in paths.items():
            descriptor, temporary = tempfile.mkstemp(prefix=prefix + "-", suffix=".tmp", dir=directory)
            temporary_paths.append(Path(temporary))
            encoding = "utf-8-sig" if key.endswith("csv_path") else "utf-8"
            with os.fdopen(descriptor, "w", encoding=encoding, newline="") as stream:
                stream.write(documents[key])
            os.replace(temporary, path)
            temporary_paths.remove(Path(temporary))
            written.append(path)
    except OSError as exc:
        cleanup_failed = False
        for path in written + temporary_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
        message = "Could not atomically write the report artifacts. Check sandbox storage access."
        if cleanup_failed:
            message += " Cleanup also failed; inspect the named run artifacts before retrying."
        raise EvidenceError("artifact_write_failed", message, "artifact_storage") from exc
    response = _transport_envelope(snapshot)
    response.update({
        "top_actions": [{
            "action_id": action["action_id"], "priority": action["priority"],
            "affected_resources": action["affected_resources"],
            **({"affected_paths": action["affected_paths"]} if "affected_paths" in action else {}),
        } for action in snapshot["actions"][:3]],
        "actions_total": len(snapshot["actions"]), "actions_returned": min(len(snapshot["actions"]), 3),
        "actions_has_more": len(snapshot["actions"]) > 3,
        **{key: str(path) for key, path in paths.items()},
    })
    return _check_transport_budget(response)
# END STANDALONE REPORT HELPERS

DEMO_LAYOUT = (
    ("Production", "PRD", 62, 28),
    ("Preproduction", "PRE", 35, 15),
    ("Dev", "DEV", 25, 10),
    ("DMZ", "DMZ", 12, 5),
    ("Backup", "BAK", 8, 0),
)
DEMO_OS_COUNTS = {
    "Windows Server 2022": 58, "Windows Server 2019": 32,
    "Red Hat Enterprise Linux": 38, "Ubuntu": 28, "SUSE Linux Enterprise": 18,
    "Debian": 14, "Windows Server 2016": 12,
}


def _fixture(reference):
    inventory, findings = [], []
    os_pool = [name for name, count in DEMO_OS_COUNTS.items() for _ in range(count)]
    reference_time = datetime.fromisoformat(reference.replace("Z", "+00:00"))
    index = 0
    for environment, abbreviation, onprem_count, gcp_count in DEMO_LAYOUT:
        for provider, count in (("onprem", onprem_count), ("gcp", gcp_count)):
            for local_index in range(1, count + 1):
                index += 1
                connectivity = (
                    "Expired" if index % 20 == 0 else
                    "Disconnected" if index % 17 == 0 else "Connected"
                )
                extension = (
                    "Missing" if index % 13 == 0 else "Failed" if index % 19 == 0 else "Succeeded"
                )
                sensor = (
                    "Unknown" if connectivity != "Connected" or extension != "Succeeded" or index % 29 == 0
                    else "Unhealthy" if index % 23 == 0 else "Healthy"
                )
                plan = "Free" if index % 21 == 0 else "P1" if index % 31 == 0 else "P2"
                days_stale = 120 if connectivity == "Expired" else 8 if connectivity == "Disconnected" else 1
                row = {
                    "resource_id": f"DEMO-ARC-{index:04d}",
                    "server_name": f"DEMO-{abbreviation}-{'ONP' if provider == 'onprem' else 'GCP'}-{local_index:03d}",
                    "resource_group": f"DEMO-{abbreviation}-{provider}",
                    "provider": provider, "provider_evidence": "SIMULATED hosting allocation, not verified customer location.",
                    "environment": environment, "os": os_pool[((index - 1) * 73) % 200],
                    "connectivity": connectivity,
                    "last_status_change_utc": (reference_time - timedelta(days=days_stale)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "last_status_change_note": "SIMULATED status-change time, not a real endpoint heartbeat.",
                    "mde_extension": extension,
                    "extension_evidence": "SIMULATED provisioning fixture: " + extension + ". Separate from sensor telemetry.",
                    "sensor_health": sensor,
                    "sensor_evidence": "SIMULATED independent sensor fixture: " + sensor + ". No MDE API was called.",
                    "servers_plan": plan, "plan_inherited": True,
                    "plan_source": "SIMULATED licence assignment; no billing or entitlement verification.",
                    "reference_utc": reference, "provenance": "SIMULATED",
                    "resource_type": "microsoft.hybridcompute/machines", "resource_kind": "Arc servers",
                    "inventory_source": "SIMULATED fixture", "parent_resource_id": "",
                    "location": "SIMULATED hosting region", "os_version": "SIMULATED",
                    "tags": {"Entorno": environment, "Responsable": "DEMO operations owner", "Departamento": "DEMO IT"},
                    "extensions": [{"name": "MDE.Windows" if "Windows" in os_pool[((index-1)*73) % 200] else "MDE.Linux",
                                    "publisher": "SIMULATED", "state": extension}],
                    "fim_configuration": "SIMULATED configured" if index % 7 == 0 else "Not verified",
                }
                inventory.append(row)
                examples = []
                if index % 9 == 0:
                    examples.append(("Vulnerability", "High", "DEMO-VA", "Synthetic outdated package finding"))
                if index % 11 == 0:
                    examples.append(("Vulnerability", "Medium", "DEMO-VA", "Synthetic configuration exposure"))
                if index % 14 == 0:
                    examples.append(("Recommendation", "Medium", "DEMO-REC", "Synthetic baseline hardening recommendation"))
                if index % 47 == 0:
                    examples.append(("Alert", "Critical", "DEMO-ALERT", "Synthetic suspicious endpoint activity"))
                for sequence, (category, severity, prefix, title) in enumerate(examples, 1):
                    findings.append({
                        "finding_id": f"{prefix}-{index:04d}-{sequence:02d}",
                        "resource_id": row["resource_id"], "server_name": row["server_name"],
                        "resource_group": row["resource_group"], "provider": provider, "environment": environment,
                        "category": category, "severity": severity,
                        "technical_severity": severity,
                        "risk_level": "Medium" if severity == "High" else "High" if category == "Alert" else "Low",
                        "status": "Active" if category == "Alert" else "Unhealthy",
                        "title": title, "source": {
                            "Recommendation": "defender_recommendations",
                            "Vulnerability": "defender_vulnerabilities", "Alert": "defender_alerts",
                        }[category],
                        "evidence": "SIMULATED deterministic fixture. DEMO identifiers are not CVEs or measured customer findings.",
                        "source_time_utc": reference, "first_evaluation_utc": reference,
                        "reference_utc": reference, "provenance": "SIMULATED",
                        "recommendation_id": prefix + "-definition",
                        "recommendation_category": "Synthetic " + category,
                        "remediation": "SIMULATED owner review: validate exposure and update/configure in an approved change window.",
                        "patch": {"software_name": "DEMO package", "detected_versions": ["DEMO-old"],
                                  "fixed_version": "DEMO-fixed", "kb": "", "source": "SIMULATED"},
                        "cve_details": ([{
                            "cve_id": f"DEMO-VA-{index:04d}-{sequence:02d}",
                            "technical_severity": severity, "fix_status": "SIMULATED fix available",
                            "fixed_version": "DEMO-fixed",
                        }] if category == "Vulnerability" else []),
                    })
                findings.append({
                    "finding_id": f"DEMO-BASELINE-{index:04d}", "recommendation_id": "DEMO-baseline-definition",
                    "resource_id": row["resource_id"], "server_name": row["server_name"],
                    "resource_group": row["resource_group"], "resource_type": row["resource_type"],
                    "provider": provider, "environment": environment,
                    "category": "Recommendation", "severity": "High", "technical_severity": "High",
                    "risk_level": "Medium" if index % 5 else "Not evaluated",
                    "status": "Unhealthy" if index % 5 else "Healthy",
                    "title": "SIMULATED review operating-system baseline",
                    "recommendation_category": "HostMisconfigurations", "source": "defender_recommendations",
                    "evidence": "SIMULATED baseline assumption; not a customer finding.",
                    "remediation": "SIMULATED: owner validates hardening, service exposure and change impact.",
                    "source_time_utc": reference, "first_evaluation_utc": reference,
                    "reference_utc": reference, "provenance": "SIMULATED", "patch": {}, "cve_details": [],
                })
    source_categories = {
        "defender_recommendations": "Recommendation", "defender_vulnerabilities": "Vulnerability",
        "defender_alerts": "Alert",
    }
    sources = [
        {
            "name": name, "status": "complete", "reference_utc": reference,
            "records": (
                sum(f["category"] == source_categories[name] for f in findings)
                if name in source_categories else len(inventory)
            ),
            "note": "SIMULATED fixture source; no Azure, external network or token acquisition.",
            "errors": [], "provenance": "SIMULATED",
        }
        for name in (
            "arc_inventory", "arc_extensions", "effective_servers_plan",
            "defender_recommendations", "defender_vulnerabilities", "defender_alerts", "mde_sensor_health",
        )
    ]
    context = _demo_context(inventory, findings, reference)
    context_records = {
        "attack_paths": context["attack_paths"], "software_inventory": context["software"],
        "secure_score_controls": context["posture"]["controls"],
        "subscription_secure_score": context["posture"]["scores"],
        "subscription_plans": context["plans"], "compliance_standards": context["compliance"]["standards"],
        "compliance_controls": context["compliance"]["controls"],
        "compliance_assessments": context["compliance"]["assessments"],
    }
    for name, records in context_records.items():
        sources.append({
            "name": name, "status": "complete", "reference_utc": reference,
            "records": len(records), "note": "SIMULATED illustrative observations, not real Defender detection/certification.",
            "errors": [], "provenance": "SIMULATED",
        })
    return _finish_snapshot(
        inventory, findings, sources, "SIMULATED", reference,
        {
            "description": "SIMULATED Mercadona-inspired demo only: 200 fictional servers, 142 on-premises / 58 GCP.",
            "customer_facts_verified": False, "azure_called": False, "token_acquired": False,
        },
        assumptions={
            "provenance": "SIMULATED",
            "server_count": 200, "hosting_counts": {"onprem": 142, "gcp": 58},
            "environment_hosting_counts": {
                env: {"onprem": onprem, "gcp": gcp} for env, _, onprem, gcp in DEMO_LAYOUT
            },
            "os_counts": DEMO_OS_COUNTS,
            "fixture_rule": "Stable integer-index rules; OS assignment is a coprime permutation of the exact 200-item pool.",
            "unsupported_claims_excluded": [
                "Invented real CVEs", "Customer attack paths", "Incident-loss ROI",
                "Automatic ENS/GDPR certification", "On-prem/GCP Arc JIT",
                "Standalone on-prem Arc agentless scanning", "All CSPM/SQL features included in Servers P2",
            ],
        },
        context=context,
    )


def _demo_context(inventory, findings, reference):
    provenance = {"provenance": "SIMULATED", "reference_utc": reference}
    paths = []
    candidates = [
        ([r for r in inventory if r["environment"] == "DMZ" and r["provider"] == "onprem"][0],
         [r for r in inventory if r["environment"] == "Production" and r["provider"] == "gcp"][0]),
        ([r for r in inventory if r["environment"] == "Production" and r["provider"] == "onprem"][0],
         [r for r in inventory if r["environment"] == "Backup"][0]),
    ]
    for number, (entry, target) in enumerate(candidates, 1):
        entities = [{
            "entity_id": f"DEMO-NODE-{number}-{i}", "name": row["server_name"],
            "resource_id": row["resource_id"], "type": "SIMULATED Arc server",
        } for i, row in enumerate((entry, target), 1)]
        paths.append({
            "path_id": f"DEMO-CHAIN-{number}", "title": "SIMULATED illustrative exposure and lateral-movement chain",
            "description": "Fictional teaching chain; not a detected Defender graph or customer topology.",
            "risk_level": "High", "risk_factors": ["SIMULATED exposure", "SIMULATED excessive access"],
            "entry_point": entities[0], "target": entities[-1], "entities": entities,
            "edges": [{"source": entities[0]["entity_id"], "target": entities[1]["entity_id"],
                       "label": "SIMULATED excessive trust relationship"}],
            "insights": [{"entity_id": entities[0]["entity_id"], "title": "SIMULATED exposure",
                          "observations": {"illustrative": True}}],
            "steps": ["SIMULATED exposed service", "SIMULATED lateral access"],
            "assessment_ids": [], "story": "Illustrative demo only: an exposed host could access another overly trusted host.",
            "remediation": "SIMULATED recommended breaks: reduce exposure, patch the host and restrict lateral permissions.",
            "partial_graph": False, "arc_resource_ids": [entry["resource_id"], target["resource_id"]],
            "resource_ids": [entry["resource_id"], target["resource_id"]],
            "association": "Arc-related", "scope": "SIMULATED Arc on-premises/GCP illustration",
            "source": "SIMULATED illustrative fixture", **provenance,
        })
    software = [{
        "software_id": "DEMO-SW-" + row["resource_id"], "resource_id": row["resource_id"],
        "server_name": row["server_name"], "software_name": "DEMO operations package",
        "version": "DEMO-1", "vendor": "SIMULATED", "known_vulnerabilities": sum(
            f["resource_id"] == row["resource_id"] and f["category"] == "Vulnerability" for f in findings
        ), "end_of_support_status": "SIMULATED supported", "arc_resource_ids": [row["resource_id"]],
        "resource_ids": [row["resource_id"]], "association": "Arc-related",
        "scope": "SIMULATED Arc fixture", "source": "SIMULATED", **provenance,
    } for row in inventory]
    baseline = [f for f in findings if f["recommendation_id"] == "DEMO-baseline-definition"]
    healthy = sum(f["status"] == "Healthy" for f in baseline)
    control = {
        "id": "DEMO-CONTROL", "name": "DEMO-baseline", "title": "SIMULATED baseline control",
        "current": healthy, "maximum": len(baseline), "percentage": healthy / len(baseline),
        "potential_score_gain": len(baseline) - healthy, "healthy": healthy,
        "unhealthy": len(baseline) - healthy, "not_applicable": 0,
        "scope": "SIMULATED illustrative control coverage, not Defender Secure Score",
        "assessment_definition_ids": ["DEMO-baseline-definition"], **provenance,
    }
    compliance_controls = [{
        "id": f"DEMO-COMPLIANCE-{i}", "name": f"DEMO-{i}", "state": state,
        "description": "SIMULATED teaching control; not certification.",
        "passedAssessments": int(state == "Passed"), "failedAssessments": int(state == "Failed"),
        "skippedAssessments": int(state == "Unsupported"), "scope": "SIMULATED", **provenance,
    } for i, state in enumerate(("Passed", "Failed", "Unsupported"), 1)]
    return {
        "attack_paths": paths, "software": software,
        "posture": {
            "scores": [{**control, "name": "DEMO-illustrative-score"}],
            "controls": [control], "risk_score_observations": [],
        },
        "plans": [{
            "name": "Servers", "pricing_tier": "SIMULATED P1/P2/Free fixture",
            "sub_plan": "Not a licence verification", "coverage": "SIMULATED",
            "scope": "Arc fixture only", **provenance,
        }],
        "compliance": {
            "standards": [{
                "name": "SIMULATED teaching baseline (not certification)", "state": "SIMULATED",
                "passedControls": 1, "failedControls": 1, "skippedControls": 0, "unsupportedControls": 1,
                "scope": "SIMULATED", **provenance,
            }], "controls": compliance_controls,
            "assessments": [{
                "id": c["id"] + "-ASSESSMENT", "name": c["name"] + "-assessment", "state": c["state"],
                "description": "SIMULATED teaching observation", "scope": "SIMULATED", **provenance,
            } for c in compliance_controls],
        },
        "subscription_recommendations": [],
    }


def main(operation: str = "report", view: str = "inventory", provider: str = "all",
         environment: str = "all", resource_group: str = "", server_name: str = "",
         connectivity: str = "all", mde: str = "all", severity: str = "all",
         limit: int = 25, offset: int = 0, risk: str = "all", status: str = "all",
         association: str = "all", resource_type: str = "") -> dict:
    """Generate clearly simulated artifacts, or query the deterministic offline demo fixture."""
    try:
        params = _validate_parameters(
            operation, view, provider, environment, resource_group, server_name,
            connectivity, mde, severity, limit, offset, risk, status, association, resource_type,
        )
        snapshot = _fixture(_utc_now())
        return _write_report(snapshot) if params["operation"] == "report" else _query(snapshot, params)
    except EvidenceError as exc:
        return _failure(exc, "SIMULATED")
