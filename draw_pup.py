import cinrad

file = r"O:\DATA\RADA\DOR\L3\PUP_ROSE2\2026\20260104\Z9437\PDP\Z_RADR_I_Z9437_20260104001745_P_DOR_CCD_PDP_150_200_5_FMT.bin"
f = cinrad.io.read_auto(file)
data = f.get_data()

print(data)