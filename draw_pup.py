import cinrad

file = r"O:\DATA\RADA\DOR\L3\PUP_ROSE2\2024\20240618\Z9439\VWP\Z_RADR_I_Z9439_20240618023825_P_DOR_CC_VWP_NUL_NUL_NUL_FMT.bin"
f = cinrad.io.read_auto(file)
vwp = f.get_data()

print(vwp)
#输出完整data数据
# print(data.variables)
# fig=cinrad.visualize.PPI(data,style='black')
# fig('test1.png')
import numpy as np
import matplotlib.pyplot as plt
import xarray
import datetime

height = np.round(np.array(vwp.height) / 1000, 1)
times = np.array(vwp.times)
times = [datetime.datetime.fromtimestamp(time, datetime.timezone.utc) for time in times]
times = [time.strftime("%H:%M") for time in times]
wind_direction = vwp.wind_direction
wind_speed = vwp.wind_speed
rms = vwp.rms
u = -wind_speed * np.sin(np.radians(wind_direction))
v = -wind_speed * np.cos(np.radians(wind_direction))


def _get_vwp_color(rms: xarray.DataArray) -> list:
    """
    风羽的颜色是由RMS值决定的。
    """
    data = rms.data
    color_map = [
        (0, "#00FF00"),
        (2, "#FFFF00"),
        (4, "#FF0000"),
        (6, "#00EFFF"),
        (8, "#FF7BFF"),
        (10, "#FFFFFF"),
    ]

    color = []
    for value in data:
        cr = color_map[0][1]
        for i in range(len(color_map)):
            if value > color_map[i][0]:
                cr = color_map[i][1]
        color.append(cr)
    return color


fig, ax = plt.subplots(1, 1, figsize=(12, 15))
ax.set_xlabel("Time(UTC)")
plt.style.use("dark_background")
ax.set_ylabel("Height (km)")
nums = np.arange(1, 31, dtype=int)
ax.set_yticks(nums, labels=height)
plt.ylim((0.5, 30))
plt.grid(True, which="both", axis="y", linestyle="--")
for i in range(len(times)):
    x = [times[i] for _ in range(len(height))]
    colors = _get_vwp_color(rms[i])
    ax.barbs(
        x,
        nums,
        u[i],
        v[i],
        rounding=False,
        barb_increments=dict(half=2, full=4, flag=20),
        sizes=dict(emptybarb=0.01, spacing=0.23, height=0.5, width=0.25),
        color=colors,
    )
plt.tight_layout()
plt.show()