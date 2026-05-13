import cinrad
file = r"O:\DATA\RADA\DOR\L3\PUP_ROSE2\2024\20240726\Z9439\R\Z_RADR_I_Z9439_20240726000317_P_DOR_CC_R_300_400_5_FMT.bin"
f = cinrad.io.read_auto(file)
data = f.get_data()
fig=cinrad.visualize.PPI(data)
fig('test1.png')