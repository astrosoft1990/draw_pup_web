import cinrad
from xarray import date_range

file = r"O:\DATA\RADA\DOR\L2\CUT\2026\20260817\Z9439\Z_RADR_I_Z9439_20260817000523_O_DOR-CUT_CC_CAP_5_1_FMT.bin.bz2"
f = cinrad.io.read_auto(file)
data = f.get_data(tilt=0,drange=200,dtype="REF")

print(data)