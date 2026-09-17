"""로컬 API에 예제 센서값을 보내는 간단한 통합 확인 스크립트."""

import json
from urllib.request import Request, urlopen


payload = {
    "readings": [
        {"MELT_TEMP": 500 + index, "MOTORSPEED": 1500, "MELT_WEIGHT": 550 - index}
        for index in range(10)
    ]
}
request = Request(
    "http://127.0.0.1:8000/predict",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urlopen(request) as response:
    print(response.read().decode())
