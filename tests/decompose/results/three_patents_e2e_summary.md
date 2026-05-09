# Decompose E2E Summary

> Note: this summary reflects the latest task_package.json files. The latest live GPT-5.5 rerun attempted after review fixes hit ChatGPT quota/rate limit; see config_driven_e2e.log.

## CN105335144B
- title: 一种车辆后备箱自动开启系统及其控制方法
- applicants: 比亚迪股份有限公司
- technology_tag: 整车与车身底盘
- claims_source: html
- model: gpt-5.5
- reasoning_effort: high
- claims: 12
- claim_1_features: 6
- claim_1_feature_texts:
  - C1-F1: 所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块
  - C1-F2: 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接
  - C1-F3: 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息
  - C1-F4: 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线
  - C1-F5: 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱
  - C1-F6: 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向

## CN114512759B
- title: 单体电池、动力电池包及电动车
- applicants: 比亚迪股份有限公司
- technology_tag: 动力电池
- claims_source: html
- model: gpt-5.5
- reasoning_effort: high
- claims: 11
- claim_1_features: 8
- claim_1_feature_texts:
  - C1-F1: 所述单体电池为硬壳电池
  - C1-F2: 所述单体电池包括： 电池本体
  - C1-F3: 所述电池本体构造为长方体形
  - C1-F4: 所述电池本体具有长度L、宽度H和和厚度D，所述电池本体的长度L大于宽度H，所述电池本体的宽度H大于厚度D
  - C1-F5: 所述电池本体的厚度D与所述电池本体的体积V满足：D/V= 0.0000065 mm ﹣2 ~0.00002mm ﹣2
  - C1-F6: 所述电池本体的表面积S与所述电池本体的能量E满足：S/E≤1000mm 2 ·Wh ﹣1
  - C1-F7: 所述电池本体的长度L为400mm~2500mm
  - C1-F8: 所述电池本体的长度L与所述电池本体的表面积S满足：L/S＝0.002mm ﹣1 ～0.005mm ﹣1

## CN107423660B
- title: 指纹识别装置、指纹识别方法和终端设备
- applicants: 比亚迪半导体股份有限公司
- technology_tag: 其他
- claims_source: pdf_vision
- model: gpt-5.5
- reasoning_effort: high
- claims: 7
- claim_1_features: 8
- claim_1_feature_texts:
  - C1-F1: 电路板
  - C1-F2: 芯片，所述芯片设置在所述电路板的上表面，所述芯片包括芯片塑料封装和芯片晶圆，所述芯片晶圆通过引线组和焊锡与所述电路板电连接
  - C1-F3: 覆盖层，所述覆盖层设置在所述芯片的上表面，且所述覆盖层上设置有图案
  - C1-F4: 所述覆盖层为喷涂在所述芯片上表面的带有图案的涂层，所述涂层由至少一种颜色涂料形成，且所述涂层不透明
  - C1-F5: 采集模块，用于采集用户指纹覆盖所述覆盖层时生成的指纹数据
  - C1-F6: 处理模块，用于根据比对数据和所述指纹数据生成修正指纹数据，并根据所述修正指纹数据进行指纹识别，所述比对数据为导电物覆盖所述覆盖层时生成的数据
  - C1-F7: 所述处理模块，具体用于： 通过如下公式计算所述修正指纹数据： $$X'=X-a*X_j$$， 其中，$X$为所述指纹数据，$X'$为所述修正指纹数据，$a$为变化系数，$X_j$为所述比对数据
  - C1-F8: 通过如下公式计算所述变化系数$a$： $$a=\frac{X_z}{b}$$， 其中，$b$为固定值，$X_z$为所述指纹数据$X$的总和
