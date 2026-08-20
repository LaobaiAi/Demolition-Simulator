# Abaqus 2026 冒烟测试脚本 v3
# 验证: 内核加载 abaqus 模块 + 创建模型 + 许可证 cae feature 检出
# 结果写入日志文件（避免 stdout 捕获问题）
from abaqus import mdb
from abaqusConstants import *
import sys, os

log_path = os.path.join(os.environ['TEMP'], 'abaqus_smoke_result.txt')
lines = []

def log(msg):
    lines.append(msg)

log("PYVER: " + sys.version.split()[0])
log("MDB_OK: " + str(mdb is not None))

try:
    m = mdb.Model(name='smoke_test')
    s = m.ConstrainedSketch(name='__profile__', sheetSize=200.0)
    s.rectangle(point1=(0.0, 0.0), point2=(10.0, 10.0))
    p = m.Part(name='block', dimensionality=THREE_D, type=DEFORMABLE_BODY)
    p.BaseSolidExtrude(sketch=s, depth=10.0)
    log("PART_OK: cells=" + str(len(p.cells)))

    m.Material(name='Steel')
    m.materials['Steel'].Elastic(table=((210000.0, 0.3),))
    p.setMeshControls(regions=p.cells, elemShape=HEX, technique=STRUCTURED)
    p.seedPart(size=5.0)
    p.generateMesh()
    log("MESH_OK: elems=" + str(len(p.elements)))
    log("SMOKE_TEST_PASSED")
except Exception as e:
    import traceback
    log("SMOKE_TEST_FAILED: " + str(e))
    log(traceback.format_exc())

with open(log_path, 'w') as f:
    f.write("\n".join(lines))
print("RESULT_WRITTEN: " + log_path)
