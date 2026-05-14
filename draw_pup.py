import cinrad
file = r"O:\DATA\RADA\DOR\L3\PUP_ROSE2\2026\20260109\Z9439\HI\Z_RADR_I_Z9439_20260109010251_P_DOR_CC_HI_NUL_200_NUL_FMT.bin"
f = cinrad.io.read_auto(file)
data = f.get_data()
print(data)
# fig=cinrad.visualize.PPI(data,style='black')
# fig('test1.png')