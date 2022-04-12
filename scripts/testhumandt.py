from utils import compactDatetime
from datetime import datetime, timedelta


a = datetime(2023, 2, 7, 10, 0)
text = compactDatetime(a)
print(text)
