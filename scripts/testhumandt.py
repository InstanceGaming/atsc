import os
import sys
from datetime import datetime


sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../src")
from utils import compactDatetime


a = datetime(2023, 2, 7, 10, 0)
text = compactDatetime(a)
print(text)
