## 1. 专利详细信息

| 字段 | 值 |
|---|---|
| 公开号 | CN105335144B |
| 标题 | 一种车辆后备箱自动开启系统及其控制方法 |
| 申请人 | BYD Co Ltd |
| 发明人 | 刘效飞、马超男、郭春光、赖楠、赵洋、赖锐 |
| 申请日 | 2014-07-31 |
| 技术领域 | 整车与车身底盘 |
| Google Patents | [https://patents.google.com/patent/CN105335144B/zh](https://patents.google.com/patent/CN105335144B/zh) |
| 官方 PDF | [https://patentimages.storage.googleapis.com/2c/07/50/136a2c800e67fc/CN105335144B.pdf](https://patentimages.storage.googleapis.com/2c/07/50/136a2c800e67fc/CN105335144B.pdf) |

> 1.一种车辆后备箱自动开启控制系统，其特征在于，所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块；
> 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接；
> 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息；
> 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线；
> 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱；
> 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向。

## 2. 整体侵权风险评估

业务侧：TOP 竞品中最高分为一数科技（ASU Tech / ASU）的 ASU AR智能投影尾门开关，候选 ID 为 P02，总分 93.33，已超过 80 分侵权风险阈值，触发侵权风险预警。该候选的核心公开卖点即“车尾地面投影 + TOF脚踩/距离检测 + 尾门自动开启”，与权利要求1的关键交互链条高度重合，应优先作为证据保全与技术拆解对象。

律师侧：权利要求1共有 6 项核心技术特征，P02 中 4 项为明确满足、2 项为可能满足；P06、P05 权1分数均为 90.0，P03 权1分数为 80.0，均达到或贴近高风险区间。P02 公开上市时间为 2019 年，晚于本专利申请日 2014-07-31，不构成因在先公开而降低侵权风险的证据；P06/P05 的上市日期仍需进一步锁定，但现有资料未显示早于申请日。需要注意，从属权利要求层面存在显著分化：P02 对权2-5及部分权6-8具较高相似度，但权7、权9-12多为证据不足；P06/P05 在权11-12出现明确不满足或证据不足，影响“是否侵权权11/权12”的判断；P03多项仅为可能满足或证据不足，需通过样品、安装手册、接线图、控制算法证据补强。

## 3. TOP5 竞品对比

#### TOP1: 一数科技 ASU AR智能投影尾门开关 MLA光学投影+TOF模组版本；地面Logo投射距离约390–400 mm，识别率宣称高于99%

| 字段 | 值 |
|---|---|
| 候选 ID | P02 |
| 公司（中/英）| 一数科技 / ASU Tech / ASU |
| 产品（中/英）| ASU AR智能投影尾门开关 / ASU AR smart projection tailgate switch |
| 产品版本 | MLA光学投影+TOF模组版本；地面Logo投射距离约390–400 mm，识别率宣称高于99% |
| 市场 | 中国汽车智能尾门前装配套/智能尾门开关系统市场 |
| 上市日期 | 2019年正式推出；2020年北京车展搭载体验；2021年已成功装车/量产化经验 |
| 总分（百分制）| 93.33 |
| 权 1 分数 | 93.33 |

**深挖理由**：该产品直接围绕“车尾地面投影+脚部踩踏/距离检测+尾门自动开启”设计，重点对应C1-F6的投影单元和脚部到投影图像检测，以及C1-F5的尾门控制触发；摘要还提到车主携带车钥匙到达车尾时车辆自动感知，值得核查其智能钥匙模块和后部天线配置以覆盖C1-F4。

**逐权利要求对比**：

##### 权利要求 1（claim_score: 93.33）

> 1.一种车辆后备箱自动开启控制系统，其特征在于，所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块；
> 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接；
> 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息；
> 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线；
> 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱；
> 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C1-F1 | 所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块 | ASU AR智能投影尾门开关公开描述为：车主带车钥匙到车尾时车辆自动感知；系统通过MLA光学投影在地面投图案，并由TOF模组检测脚踩动作；TOF检测后发出指令使尾门自动打开，官网还列出CAN/LIN/高低电平控制接口。 | 明确满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [一数科技官网](http://a-su.com.cn/3-1.html) | 公开页面直接披露钥匙感知、MLA投影+TOF检测以及尾门控制/控制接口，分别对应智能钥匙、信息采集和后备箱控制三类模块。 |
| C1-F2 | 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接 | 信息采集侧TOF模组“检测并发出指令”使尾门自动打开；官网称AR尾门开关具有CAN、LIN、可控高低电平接口。车钥匙到车尾后车辆自动感知并触发投影/检测流程，说明钥匙感知信号进入车辆尾门控制链路，但未见公开线束/电路图逐项标明连接。 | 可能满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [一数科技官网](http://a-su.com.cn/3-1.html) | CAN/LIN/高低电平是电气控制接口；TOF“发出指令”后尾门开启可严谨推知信息采集模块接入尾门控制。但钥匙模块到尾门控制的具体电连接未直接公开。 |
| C1-F3 | 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息 | 产品安装/作用区域为车尾/尾门：车主到达车尾后系统感知，在距尾门一定距离的地面投图案；技术参数公开投影高度1m、投影与车尾距离0.6–0.7m，另有报道称Logo图案投射距离车尾390–400mm；TOF模组用于精确定位/检测脚踩动作。 | 明确满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [砍柴网](https://m.ikanchai.com/pcarticle/437409)<br>3. [一数科技官网](http://www.a-su.com.cn/3-3.html) | 车尾/尾门区域参数给出相对尾门距离；TOF公开为汽车定位传感并用于脚踩检测，能获取用户脚部相对车尾投影区的位置/距离信息。 |
| C1-F4 | 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线 | 公开资料称车主携带车钥匙或蓝牙钥匙到达车尾部安全距离时，车辆会自动感知，然后触发地面投影/检测流程。该事实支持钥匙端存在可被车辆探测的钥匙信号单元；车尾区域感知通常需车辆侧探测器/天线参与，但未直接公开“设置在后备箱的探测天线”。 | 可能满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [北京日报客户端](https://xinwen.bjd.com.cn/content/s5f74463fe4b03c6143a9f971.html)<br>3. [新浪财经头条](https://t.cj.sina.com.cn/articles/view/1224807694/4901150e00100z3g9) | “蓝牙钥匙/车钥匙到车尾即被感知”直接证明钥匙与车辆侧探测配合；但公开证据未字面披露后备箱探测天线位置，因此只能认定可能满足。 |
| C1-F5 | 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱 | ASU系统在车主踩踏地面投影后，由TOF模组准确检测并发出指令，尾门在保障安全距离情况下自动打开；官网显示AR尾门开关具有CAN、LIN、可控高低电平接口，可与整车尾门执行/控制系统交互。 | 明确满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [一数科技官网](http://a-su.com.cn/3-1.html)<br>3. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | TOF检测脚踩信息后“发出指令”并使尾门自动打开，且官网给出CAN/LIN等控制接口，直接支撑根据检测信息判断并启动尾门开启。 |
| C1-F6 | 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向 | ASU产品采用MLA光学投影在车尾地面投射Logo/图案，用户轻踩图案；TOF模组准确检测脚踩动作并发出指令。参数：投影logo尺寸10cm×10cm，投影高度1m，投影与车尾距离0.6–0.7m；另有报道称地面Logo距离车尾390–400mm。 | 明确满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [砍柴网](https://m.ikanchai.com/pcarticle/437409)<br>3. [新浪财经头条](https://t.cj.sina.com.cn/articles/view/1224807694/4901150e00100z3g9)<br>4. [一数科技官网](http://www.a-su.com.cn/3-3.html) | MLA为投射图像单元；TOF为距离/定位检测单元。证据明确为车尾向地面投图案并检测脚踩图案，投影高度/车尾距离参数进一步支持下向地面布置。 |

##### 权利要求 2（claim_score: 90.0）

> 2.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述投影单元为可投射影像的激光投影仪，所述距离检测单元为直线距离传感器。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C2-F1 | 所述投影单元为可投射影像的激光投影仪 | ASU AR尾门开关采用MLA光学投影在地面投射Logo/图案；北京日报报道其在车主带蓝牙钥匙到达车尾安全距离时“释放一束激光在地面投射出品牌Logo”。 | 明确满足 | 1. [北京日报客户端](https://xinwen.bjd.com.cn/content/s5f74463fe4b03c6143a9f971.html)<br>2. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html) | “释放一束激光在地面投射品牌Logo”直接对应可投射影像的激光投影单元；技术参数也披露其投影图案和亮度/高度。 |
| C2-F2 | 所述距离检测单元为直线距离传感器 | ASU公开使用TOF模组准确检测脚踩动作；一数科技官网的ASU ToF T1/T2/T3激光ToF模组适用于汽车电子定位传感，具有“工作距离长，精确定位”的特征。TOF通常通过光飞行时间测量传感器到目标的直线/视线距离，但公开材料未直接称其为“直线距离传感器”。 | 可能满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [一数科技官网](http://www.a-su.com.cn/3-3.html) | TOF激光模组的基本测量机理是测距/定位，且产品场景为检测用户脚踩地面投影。由于资料没有字面披露“直线距离传感器”或具体测距输出，因此保守评为可能满足。 |

##### 权利要求 3（claim_score: 80.0）

> 3.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C3-F1 | 所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启 | ASU系统公开的工作链路为：携带钥匙靠近车尾后系统自动感知，随后投影；用户轻踩投影后TOF模组准确检测并发出指令，尾门自动打开。官网还披露CAN、LIN、可控高低电平接口。公开资料能推知存在电控/控制接口接收钥匙感知和TOF检测信息并控制尾门，但未直接公开具体ECU名称、控制器框图或判断逻辑。 | 可能满足 | 1. [一数科技官网](http://a-su.com.cn/3-1.html)<br>2. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>3. [一数科技官网](http://a-su.com.cn/html/news20210401.html) | CAN/LIN/高低电平接口及“检测并发出指令”说明系统具有电控判断与执行接口；但没有公开资料直接指认后备箱控制模块中的ECU及其接收两路信息的内部逻辑，因此为可能满足。 |

##### 权利要求 4（claim_score: 80.0）

> 4.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C4-F1 | 所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱 | 公开报道将该产品应用于“电动尾门/智能尾门”开启，踩踏投影后尾门自动打开。电动尾门通常由电机/撑杆等执行器开启，但ASU公开资料主要披露AR尾门开关及其控制接口，未直接披露其自身或配套后备箱控制模块包括安装在后备箱的开启电机。 | 可能满足 | 1. [搜狐汽车/TechWeb](https://www.sohu.com/a/459444421_170520)<br>2. [一数科技官网](http://a-su.com.cn/3-1.html) | “电动尾门自动打开”强烈指向车辆后备箱存在电机/电动执行机构；但证据未直接说明ASU系统的后备箱控制模块包括开启电机及其安装位置，故不能评为明确满足。 |

##### 权利要求 5（claim_score: 86.67）

> 5.一种车辆后备箱自动开启控制系统的控制方法，所述控制方法应用于权利要求1-4任一项所述的车辆后备箱自动开启控制系统，其特征在于，包括以下步骤：
> 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息；
> 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块；
> 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C5-F1 | 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息 | ASU公开流程为用户携带车钥匙/蓝牙钥匙靠近车尾时，系统会自动感知并开始投影。该流程体现了从非车尾区域到车尾附近的靠近状态触发，但公开材料未直接说明“从远至近的位置变化信息”被反馈至后备箱控制模块。 | 可能满足 | 1. [新浪财经头条](https://t.cj.sina.com.cn/articles/view/1224807694/4901150e00100z3g9)<br>2. [北京日报客户端](https://xinwen.bjd.com.cn/content/s5f74463fe4b03c6143a9f971.html) | “携带钥匙靠近车尾/到达安全距离被感知”与从远至近的钥匙状态变化高度一致；但反馈路径和位置变化信息格式未公开。 |
| C5-F2 | 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块 | ASU在车尾地面投射图案，用户轻踩图案后TOF模组准确检测并发出指令；技术参数给出投影与车尾距离0.6–0.7m，另有Logo距离车尾390–400mm。公开证据表明其采集脚踩投影区域状态并反馈/发出指令，但未直接披露“人脚与后备箱的距离状态信息”这一数据字段。 | 可能满足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | 固定投影区与车尾之间的距离参数，加上TOF检测脚踩动作，可推知采集的是脚部相对投影/车尾区域的状态并用于控制；但没有公开到“人脚与后备箱距离状态信息”的直接描述。 |
| C5-F3 | 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启 | ASU公开工作顺序为：车主带钥匙到达车尾车辆自动感知；系统投射图案；车主轻踩后TOF模组准确检测并发出指令；尾门在保障安全距离情况下自动打开。 | 明确满足 | 1. [一数科技官网](http://a-su.com.cn/html/news20210401.html)<br>2. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html) | 公开流程明确要求钥匙感知和TOF脚踩检测共同形成开启链路，并由系统发出指令控制尾门开启，满足该高层方法步骤。 |

##### 权利要求 6（claim_score: 55.0）

> 6.根据权利要求5所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元，
> 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；
> 当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C6-F1 | 步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元 | ASU公开称车主带车钥匙/蓝牙钥匙到达车尾部安全距离时车辆自动感知，随后投影。该证据支持车辆侧对钥匙靠近车尾状态进行检测并触发控制流程，但未直接披露“探测天线”、钥匙感应单元、从远至近状态变化信息及反馈到电控单元的具体实现。 | 可能满足 | 1. [北京日报客户端](https://xinwen.bjd.com.cn/content/s5f74463fe4b03c6143a9f971.html)<br>2. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html) | 蓝牙钥匙/车钥匙到车尾被车辆感知，通常需要车辆侧天线或接收器；但由于公开资料没有逐项披露天线位置和ECU反馈路径，只能认定可能满足。 |
| C6-F2 | 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；<br>当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2 | ASU公开材料只披露当用户携带钥匙靠近车尾时系统自动感知并进入投影/脚踩检测流程；未披露钥匙不存在从远至近变化时的返回重新检测逻辑，也未披露ECU分支判断流程。 | 证据不足 | [一数科技官网](http://a-su.com.cn/html/news20210401.html) | 证据仅说明满足钥匙靠近条件后的下一步动作；没有公开“未检测到则返回重新检测/检测到则进入S2”的完整循环控制逻辑。 |

##### 权利要求 7（claim_score: 30.0）

> 7.根据权利要求6所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C7-F1 | 当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪 | ASU公开材料披露用户携带钥匙靠近车尾后系统自动感知，并在地面投射Logo/图案；但没有公开电控单元发送“脉冲信号”开启激光投影仪的内部电信号形式。 | 证据不足 | 1. [北京日报客户端](https://xinwen.bjd.com.cn/content/s5f74463fe4b03c6143a9f971.html)<br>2. [一数科技官网](http://a-su.com.cn/3-1.html) | 钥匙靠近后开启投影这一外部流程有证据；但“脉冲信号”是更窄的内部控制方式，公开资料未披露，不能严谨推定。 |

##### 权利要求 8（claim_score: 55.0）

> 8.根据权利要求7所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n)，设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C8-F1 | 步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n) | ASU公开采用激光/MLA光学投影在地面投射Logo，TOF模组准确检测脚踩动作并发出指令，响应速度<0.5s。TOF模组通常进行距离/定位检测，因此可能实时采集测距值并反馈控制单元；但公开资料未直接披露D、D1…Dn这类投射实际距离序列及其反馈方式。 | 可能满足 | 1. [搜狐汽车/TechWeb](https://www.sohu.com/a/459444421_170520)<br>2. [一数科技官网](http://www.a-su.com.cn/3-3.html) | 投影到地面和TOF检测明确公开；TOF定位传感器可合理推知存在测距/定位数据。但该从属权利要求的连续D值采集和反馈到ECU未被直接披露，因此仅为可能满足。 |
| C8-F2 | 设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di | 未见ASU公开资料披露其算法将投射实际距离最大值Di设为基准值C，或任何关于C、D、最大值基准的阈值/标定算法。 | 证据不足 | [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html) | 公开参数仅是投影尺寸、高度、车尾距离和响应速度，未披露基准值C的计算规则或最大距离Di赋值逻辑。 |

##### 权利要求 9（claim_score: 30.0）

> 9.根据权利要求8所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C9-F1 | 步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上 | ASU公开资料披露TOF模组准确检测脚踩图案并发出指令，但未披露C与D差值阈值≤1cm，也未披露该条件下判断“人脚没有放置到地面影像上”的算法。 | 证据不足 | [一数科技官网](http://a-su.com.cn/html/news20210401.html) | 脚踩检测有公开证据，但具体1cm阈值和无脚判断逻辑没有公开。 |

##### 权利要求 10（claim_score: 30.0）

> 10.根据权利要求9所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C10-F1 | 当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像 | ASU公开资料未披露C与D差值≤1cm、持续时间t1或因未踩踏/无脚状态持续而熄灭投影影像的控制策略。 | 证据不足 | [搜狐汽车/TechWeb](https://www.sohu.com/a/459444421_170520) | 公开资料虽有投影参数和响应速度，但没有披露投影熄灭条件、t1计时或1cm阈值。 |

##### 权利要求 11（claim_score: 30.0）

> 11.根据权利要求9或10所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3，还包括以下步骤：
> 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上；
> 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C11-F1 | 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上 | ASU公开资料披露用户轻踩图案后TOF模组准确检测并发出指令，但未披露以C与D差值>1cm且<8cm作为判断脚落在影像上的阈值。 | 证据不足 | [砍柴网](https://m.ikanchai.com/pcarticle/437409) | 存在脚踩检测，但1cm到8cm的数值区间阈值未公开。 |
| C11-F2 | 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测 | ASU公开资料未披露C与D差值≥8cm时返回钥匙检测步骤S1进行重新检测的分支流程。 | 证据不足 | [一数科技官网](http://a-su.com.cn/html/news20210401.html) | 公开资料没有8cm阈值，也没有失败/异常检测后返回S1的循环控制算法。 |

##### 权利要求 12（claim_score: 30.0）

> 12.根据权利要求11所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，
> 如果是，所述电控单元控制开启后备箱；
> 否则，返回S1进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C12-F1 | 当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，<br>如果是，所述电控单元控制开启后备箱；<br>否则，返回S1进行重新检测 | ASU公开资料披露轻踩投影后TOF模组检测并发出指令，尾门自动打开；未披露蜂鸣器提示，也未披露>1cm且<8cm状态持续t2秒后开启、否则返回S1的完整控制逻辑。 | 证据不足 | 1. [新浪科技/TechWeb](https://tech.sina.cn/2021-04-07/detail-ikmxzfmk5483873.d.html)<br>2. [一数科技官网](http://a-su.com.cn/3-1.html) | 尾门开启的最终动作有证据，但蜂鸣器、t2持续时间、1-8cm阈值和失败返回S1均没有公开披露。 |

#### 该候选的证据缺口（如有）

- 权1 C1-F2（可能满足）：建议下一步人工搜索。
- 权1 C1-F4（可能满足）：建议下一步人工搜索。
- 权2 C2-F2（可能满足）：建议下一步人工搜索。
- 权3 C3-F1（可能满足）：建议下一步人工搜索。
- 权4 C4-F1（可能满足）：建议下一步人工搜索。
- 权5 C5-F1（可能满足）：建议下一步人工搜索。
- 权5 C5-F2（可能满足）：建议下一步人工搜索。
- 权6 C6-F1（可能满足）：建议下一步人工搜索。
- 权6 C6-F2（证据不足）：建议下一步人工搜索。
- 权7 C7-F1（证据不足）：建议下一步人工搜索。
- 权8 C8-F1（可能满足）：建议下一步人工搜索。
- 权8 C8-F2（证据不足）：建议下一步人工搜索。
- 权9 C9-F1（证据不足）：建议下一步人工搜索。
- 权10 C10-F1（证据不足）：建议下一步人工搜索。
- 权11 C11-F1（证据不足）：建议下一步人工搜索。
- 权11 C11-F2（证据不足）：建议下一步人工搜索。
- 权12 C12-F1（证据不足）：建议下一步人工搜索。

#### TOP2: 凯迪拉克（通用汽车） 免手动电动尾门（带标志投影） 标志投影+可编程开启高度版本

| 字段 | 值 |
|---|---|
| 候选 ID | P06 |
| 公司（中/英）| 凯迪拉克（通用汽车） / Cadillac / General Motors |
| 产品（中/英）| 免手动电动尾门（带标志投影） / Hands-Free Power Liftgate with logo projection |
| 产品版本 | 标志投影+可编程开启高度版本 |
| 市场 | 通用汽车凯迪拉克品牌SUV/跨界车电动尾门配置；需核查中国在售车型配置表 |
| 上市日期 | 未明确（公开证据至少显示2018款凯雷德已有脚踢电尾门；带Logo投影的XT6公开说明见2025年4月） |
| 总分（百分制）| 90.0 |
| 权 1 分数 | 90.0 |

**深挖理由**：公开摘要显示其以Logo投影提示脚踢区域并由保险杠下方脚部动作控制电动尾门，具备权利要求1最关键的C1-F6“投影单元+脚部检测”线索；下游应进一步锁定中国销售车型、车尾投影器/传感器位置和智能钥匙天线认证逻辑。

**逐权利要求对比**：

##### 权利要求 1（claim_score: 90.0）

> 1.一种车辆后备箱自动开启控制系统，其特征在于，所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块；
> 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接；
> 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息；
> 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线；
> 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱；
> 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C1-F1 | 所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块 | 凯迪拉克Hands-Free Power Liftgate with logo projection包含：位于车尾/保险杠下方的脚踢传感与Logo投影，用于采集脚部动作；key fob/RKE发射器用于智能钥匙识别；举升门控制模块、车身控制模块或Hands Free Liftgate/Rear Closure Module用于控制电动举升门。 | 明确满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Xtooltech](https://www.xtooltech.com/official/pack_pdf/PS_ZGCADILLAC/PS_ZGCADILLAC_V17_10_CN.pdf)<br>3. [GMPartsDirect](https://www.gmpartsdirect.com/oem-parts/gm-hands-free-liftgate-module-23275430) | 官方支持页直接披露key fob、Logo投影/脚踢感应和电动举升门；Xtool功能表与GM零件页进一步列出无钥匙进入控制模块、举升门控制模块/Hands Free Liftgate Module，可对应三类模块。 |
| C1-F2 | 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接 | 公开资料显示脚踢传感、Logo投影、key fob识别与举升门/车身控制模块共同工作：钥匙进入后方检测区后Logo投影点亮，脚踢传感后举升门开启；2024 XT4该功能可通过重新编程Body Control Module修复；论坛亦提及XT5加装“Hands Free Module and Sensors”时“required wiring already exists”。但公开资料未给出完整线束/总线拓扑图来逐字证明各模块均与后备箱控制模块电连接。 | 可能满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Cadillac Society](https://cadillacsociety.com/2024/02/23/2024-cadillac-xt4-to-fix-hands-free-liftgate-via-software-update)<br>3. [Cadillac Owners Forum](https://www.cadillacforums.com/threads/hands-free-liftgate-control.1091114) | 功能链条和维修/软件更新证据强烈表明传感、钥匙和控制模块通过车辆电气系统联动；但缺少适用于该Logo投影版本的官方电气连接图或接插件定义，故保守评为可能满足。 |
| C1-F3 | 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息 | 脚踢传感区域位于后保险杠下方/后保险杠中心或侧后区域；操作要求脚部以直进直出的动作踢向车身下方，并在保险杠或传感器约5英寸/12.7 cm范围内，RKE钥匙需在举升门约3英尺/1 m内。 | 明确满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [GM-Trucks.com](https://www.gm-trucks.com/forums/topic/251196-troubleshooting-the-hands-free-liftgate-not-working-when-i-kick-underneath)<br>3. [BitAuto](https://www.bitauto.com/ask/100319653468) | 后保险杠下方/后保险杠中心属于车辆后备箱/举升门区域；5英寸距离阈值和脚踢感应说明其获取用户脚部相对于车尾传感区的距离/位置状态。 |
| C1-F4 | 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线 | 系统要求用户携带key fob/RKE transmitter接近车尾；key fob进入车尾约6英尺检测区时Logo投影自动点亮，进入约3英尺范围时允许免手动尾门操作；NHTSA公告也将“RKE Transmitter within detection zone”与Projected Logo工作状态关联。未直接公开后备箱处“探测天线”的实体或位置。 | 可能满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [NHTSA / GM Service Bulletin](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf)<br>3. [Cadillac官方支持](https://www.cadillac.com/support/quick-start-guides/autosense-liftgate) | 后方限定距离内识别key fob可严谨推定钥匙内有被识别的RKE/钥匙感应单元，车辆后部有相应接收/检测硬件；但证据未直接给出后备箱探测天线，故为可能满足。 |
| C1-F5 | 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱 | 电动举升门在检测到合规脚踢动作后自动开启/关闭；系统会在开闭前闪灯、鸣响并可设置开启高度；维修/诊断资料列出举升门控制模块、车身控制模块、Hands Free Liftgate Module、liftgate motor assembly等控制与执行部件。 | 明确满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Xtooltech](https://www.xtooltech.com/official/pack_pdf/PS_ZGCADILLAC/PS_ZGCADILLAC_V17_10_CN.pdf)<br>3. [Portal-Diagnostov](https://portal-diagnostov.com/en/2020/04/06/trunk-tailgate-fuel-door-cadillac-srx-2014-system-wiring-diagrams) | 官方操作页直接说明脚踢信号触发电动举升门；诊断/线路资料确认存在举升门控制模块和电机/锁止等执行单元，可对应后备箱控制单元与启动单元。 |
| C1-F6 | 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向 | 系统具有向地面投射Cadillac Logo的projected logo lamp/illuminated logo projection，用于指示踢脚位置；脚踢传感器位于后保险杠下方或后保险杠中心，用户需kick straight over the logo并使脚接近保险杠/传感器5英寸内。公开证据证明有投影单元和车尾下方脚部传感/距离阈值，但未字面说明该传感器测量“脚部到投影图像”的直线距离。 | 可能满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [BitAuto](https://www.bitauto.com/ask/100319653468)<br>3. [GM-Trucks.com](https://www.gm-trucks.com/forums/topic/251196-troubleshooting-the-hands-free-liftgate-not-working-when-i-kick-underneath) | 投影灯向地面投射Logo且传感器位于车尾下方，功能上以Logo为目标检测脚部动作；但证据仅公开对保险杠/传感器的5英寸阈值，未公开测量脚部到投影图像的距离，因此为可能满足。 |

##### 权利要求 2（claim_score: 30.0）

> 2.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述投影单元为可投射影像的激光投影仪，所述距离检测单元为直线距离传感器。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C2-F1 | 所述投影单元为可投射影像的激光投影仪 | 公开资料称为“logo projection”“illuminated logo projection”或“projected logo lamp”，可以投射Logo影像，但未披露其光源/器件为激光投影仪；“projected logo lamp”更接近投影灯而非明确的激光投影仪。 | 证据不足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Cadillac Society](https://cadillacsociety.com/2024/02/23/2024-cadillac-xt4-to-fix-hands-free-liftgate-via-software-update) | 证据能证明投射影像/Logo，但不能证明投影单元采用“激光投影仪”这一更窄限定。 |
| C2-F2 | 所述距离检测单元为直线距离传感器 | 公开资料仅称hands-free sensor/foot sensor位于保险杠下方，脚部动作需在传感器或保险杠5英寸内；未披露其为直线距离传感器，也未披露输出线性距离测量值。 | 证据不足 | 1. [GM-Trucks.com](https://www.gm-trucks.com/forums/topic/251196-troubleshooting-the-hands-free-liftgate-not-working-when-i-kick-underneath)<br>2. [Arrowhead Cadillac](https://www.arrowheadcadillac.com/blog/2020/november/13/how-to-use-the-cadillac-hands-free-liftgate-power-trunk.htm) | “5英寸内触发”证明存在近距脚部传感，但传感器类型和是否为直线距离传感器未公开。 |

##### 权利要求 3（claim_score: 100.0）

> 3.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C3-F1 | 所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启 | 凯迪拉克/GM系统存在举升门控制模块、车身控制模块及Hands Free Liftgate/Rear Closure Module；系统根据key fob/RKE在检测区和脚踢传感信息来开启举升门；2024 XT4相关故障通过重新编程Body Control Module解决。 | 明确满足 | 1. [Cadillac Society](https://cadillacsociety.com/2024/02/23/2024-cadillac-xt4-to-fix-hands-free-liftgate-via-software-update)<br>2. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>3. [GM Parts Warehouse](https://www.gmpartswarehouse.com/oem-parts/gm-hands-free-rear-closure-module-23460553) | Body Control Module/Hands Free Rear Closure Module属于电控单元；官方操作逻辑要求钥匙与脚踢传感共同满足后才开启举升门，能证明电控单元接收判断这些信息并控制开启。 |

##### 权利要求 4（claim_score: 100.0）

> 4.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C4-F1 | 所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱 | Power Liftgate为电动举升门；Cadillac SRX线路资料列出Liftgate motor assembly、Latch motor open/close control和Liftgate control module，GM零件资料也将Hands Free Rear Closure Module描述为Liftgate motor control。 | 明确满足 | 1. [Portal-Diagnostov](https://portal-diagnostov.com/en/2020/04/06/trunk-tailgate-fuel-door-cadillac-srx-2014-system-wiring-diagrams)<br>2. [GM Parts Warehouse](https://www.gmpartswarehouse.com/oem-parts/gm-hands-free-rear-closure-module-23460553)<br>3. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 电动举升门的开启/关闭由举升门电机组件执行，线路资料明确列有liftgate motor assembly，位置在cargo/liftgate区域，可对应安装在车辆后备箱并用于开启后备箱的开启电机。 |

##### 权利要求 5（claim_score: 93.33）

> 5.一种车辆后备箱自动开启控制系统的控制方法，所述控制方法应用于权利要求1-4任一项所述的车辆后备箱自动开启控制系统，其特征在于，包括以下步骤：
> 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息；
> 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块；
> 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C5-F1 | 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息 | Cadillac官方说明要求携带key fob从车后方接近；Logo投影在用户进入车尾6英尺内自动点亮。AutoSense资料还明确要求从超过10英尺外接近至3英尺内，体现从远至近的位置状态变化。内部反馈到后备箱控制模块未以信号流形式公开。 | 可能满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Cadillac官方支持](https://www.cadillac.com/support/quick-start-guides/autosense-liftgate)<br>3. [NHTSA / GM Service Bulletin](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf) | 公开资料直接披露key fob由远及近进入检测区会引发Logo/尾门系统响应；因未公开“反馈到后备箱控制模块”的内部报文或硬线，保守为可能满足。 |
| C5-F2 | 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块 | 脚踢传感器采集脚部相对于后保险杠/传感器的距离和动作状态；用户脚部需在保险杠或传感器约5英寸内并进行直进直出动作，系统才触发举升门。 | 明确满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [GM-Trucks.com](https://www.gm-trucks.com/forums/topic/251196-troubleshooting-the-hands-free-liftgate-not-working-when-i-kick-underneath) | 5英寸阈值和规定脚踢动作即人脚与后备箱/传感器的距离状态；系统据此开启举升门，说明该状态被传递给控制逻辑。 |
| C5-F3 | 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启 | 系统要求key fob在车辆/举升门近距离范围内，并检测到正确脚踢动作后才开启；控制逻辑涉及Body Control Module/Hands Free Rear Closure Module。 | 明确满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Cadillac Society](https://cadillacsociety.com/2024/02/23/2024-cadillac-xt4-to-fix-hands-free-liftgate-via-software-update) | 官方操作条件同时包含钥匙近距和脚踢检测；满足后电动举升门开启，且Body Control Module软件可影响该功能，足以证明控制模块对两类信息进行判断并控制开启。 |

##### 权利要求 6（claim_score: 80.0）

> 6.根据权利要求5所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元，
> 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；
> 当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C6-F1 | 步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元 | AutoSense/Logo投影相关资料显示系统检测key fob/RKE从10英尺外接近至3英尺或6英尺内；NHTSA资料称RKE transmitter进入detection zone时Projected Logo工作。未直接公开“探测天线”及向电控单元反馈的具体信号。 | 可能满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/quick-start-guides/autosense-liftgate)<br>2. [NHTSA / GM Service Bulletin](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf)<br>3. [Cadillac Society](https://cadillacsociety.com/2024/02/23/2024-cadillac-xt4-to-fix-hands-free-liftgate-via-software-update) | 由远至近的RKE/key fob检测公开明确；结合BCM软件控制可推定反馈至电控单元。但探测天线实体和信号链未公开，故为可能满足。 |
| C6-F2 | 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；<br>当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2 | AutoSense资料要求使用者先离车超过10英尺并保持一段时间，再从至少10英尺外接近车尾；若key fob长时间停留在10英尺范围内会被muted/unresponsive，需重新触发/重新接近。这与“没有从远至近变化则不触发、存在从远至近变化则进入下一步”逻辑相近，但未逐字披露返回S1/进入S2流程。 | 可能满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/quick-start-guides/autosense-liftgate)<br>2. [NHTSA / GM Service Bulletin](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf) | 证据证明GM/Cadillac系统对RKE从远至近和重复进出检测区有状态机处理；不过没有公开专利式的“返回重新检测/进入步骤S2”流程图，故为可能满足。 |

##### 权利要求 7（claim_score: 80.0）

> 7.根据权利要求6所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C7-F1 | 当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪 | 凯迪拉克官方资料显示key fob进入车尾约6英尺时Logo projection自动点亮；NHTSA公告显示RKE transmitter在检测区内时Projected Logo为On，Cadillac Society显示该功能受Body Control Module软件控制。未披露控制信号为“脉冲信号”，也未证明投影器为“激光投影仪”。 | 可能满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [NHTSA / GM Service Bulletin](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf)<br>3. [Cadillac Society](https://cadillacsociety.com/2024/02/23/2024-cadillac-xt4-to-fix-hands-free-liftgate-via-software-update) | “钥匙进入检测区→投影Logo自动点亮”与本特征的触发关系高度一致；但脉冲信号形式和激光投影仪类型未公开，只能评为可能满足。 |

##### 权利要求 8（claim_score: 30.0）

> 8.根据权利要求7所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n)，设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C8-F1 | 步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n) | 竞品公开资料证明Logo投影在地面显示、脚部动作需在传感器/保险杠5英寸内，但未披露激光投影仪、直线距离传感器、实时检测传感器到投影影像距离D、D1...Dn序列或将D反馈给电控单元。 | 证据不足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [GM-Trucks.com](https://www.gm-trucks.com/forums/topic/251196-troubleshooting-the-hands-free-liftgate-not-working-when-i-kick-underneath) | 已有证据只披露投影和脚踢近距触发，无法证明专利中D值连续测量与反馈机制。 |
| C8-F2 | 设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di | 未发现凯迪拉克/GM公开资料披露设定投射距离基准值C、取投射实际距离最大值Di并令C=Di的算法或参数。 | 证据不足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [NHTSA / GM Service Bulletin](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf) | 公开资料属于操作说明/服务公告，没有披露C、D、Di等控制算法变量。 |

##### 权利要求 9（claim_score: 30.0）

> 9.根据权利要求8所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C9-F1 | 步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上 | 公开资料未披露C、D差值，更未披露≤1 cm阈值及据此判断人脚未放置到投影影像上的逻辑。竞品公开的量化阈值是脚踢动作需在保险杠/传感器约5英寸内。 | 证据不足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [GM-Trucks.com](https://www.gm-trucks.com/forums/topic/251196-troubleshooting-the-hands-free-liftgate-not-working-when-i-kick-underneath) | 5英寸脚踢阈值不同于专利C-D≤1 cm算法；无证据显示竞品有该判断。 |

##### 权利要求 10（claim_score: 30.0）

> 10.根据权利要求9所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C10-F1 | 当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像 | NHTSA公告披露Projected Logo在RKE进入检测区时可点亮1分钟，并在某些条件下关闭；AutoSense资料也有长时间停留导致功能muted的逻辑。但没有披露C-D≤1 cm、持续t1秒、据此熄灭激光投影影像的算法。 | 证据不足 | 1. [NHTSA / GM Service Bulletin](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf)<br>2. [Cadillac官方支持](https://www.cadillac.com/support/quick-start-guides/autosense-liftgate) | 竞品确有投影灯关闭/超时状态管理，但与专利的C-D≤1 cm+t1秒条件无公开对应关系。 |

##### 权利要求 11（claim_score: 0.0）

> 11.根据权利要求9或10所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3，还包括以下步骤：
> 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上；
> 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C11-F1 | 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上 | 凯迪拉克官方明确要求“kick straight over the logo”，并提示“stepping on the logo projection will not activate the sensor”；其量化要求是脚部接近保险杠约5英寸/12.7 cm，而非C-D大于1 cm且小于8 cm时判断脚落在投影影像上。 | 明确不满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [GM-Trucks.com](https://www.gm-trucks.com/forums/topic/251196-troubleshooting-the-hands-free-liftgate-not-working-when-i-kick-underneath) | 本从属特征核心是判断脚“落在地面的影像上”；竞品官方说明直接指出踩/落在Logo投影上不会激活传感器，而是要求直进直出踢过Logo，故该从属方法特征被直接否定。 |
| C11-F2 | 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测 | 未发现公开资料披露C-D≥8 cm阈值或据此返回S1重新检测的逻辑；竞品公开的距离阈值为脚踢动作须在保险杠/传感器约5英寸内。 | 证据不足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Cadillac官方支持](https://www.cadillac.com/support/quick-start-guides/autosense-liftgate) | 3英尺取消/5英寸触发等操作阈值不能证明专利的8 cm阈值与返回S1流程。 |

##### 权利要求 12（claim_score: 0.0）

> 12.根据权利要求11所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，
> 如果是，所述电控单元控制开启后备箱；
> 否则，返回S1进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C12-F1 | 当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，<br>如果是，所述电控单元控制开启后备箱；<br>否则，返回S1进行重新检测 | 竞品在识别到正确脚踢动作后会有约2秒延迟、后灯闪烁和chime提示并开启举升门；但官方同时明确“stepping on the logo projection will not activate the sensor”，即脚落在地面Logo影像上并保持并不会触发开启。未披露C-D 1到8 cm持续t2秒的判断。 | 明确不满足 | 1. [Cadillac官方支持](https://www.cadillac.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Cadillac官方支持](https://www.cadillac.com/support/quick-start-guides/autosense-liftgate) | 虽然竞品有蜂鸣/提示和延迟开启，但其公开操作方式与本特征“脚落在地面影像上并持续t2秒后开启”相反：官方明示踩在Logo投影上不会激活传感器。 |

#### 该候选的证据缺口（如有）

- 权1 C1-F2（可能满足）：建议下一步人工搜索。
- 权1 C1-F4（可能满足）：建议下一步人工搜索。
- 权1 C1-F6（可能满足）：建议下一步人工搜索。
- 权2 C2-F1（证据不足）：建议下一步人工搜索。
- 权2 C2-F2（证据不足）：建议下一步人工搜索。
- 权5 C5-F1（可能满足）：建议下一步人工搜索。
- 权6 C6-F1（可能满足）：建议下一步人工搜索。
- 权6 C6-F2（可能满足）：建议下一步人工搜索。
- 权7 C7-F1（可能满足）：建议下一步人工搜索。
- 权8 C8-F1（证据不足）：建议下一步人工搜索。
- 权8 C8-F2（证据不足）：建议下一步人工搜索。
- 权9 C9-F1（证据不足）：建议下一步人工搜索。
- 权10 C10-F1（证据不足）：建议下一步人工搜索。
- 权11 C11-F2（证据不足）：建议下一步人工搜索。

#### TOP3: 别克（通用汽车） 免手动电动尾门（带标志投影） 标志投影+可编程开启高度版本

| 字段 | 值 |
|---|---|
| 候选 ID | P05 |
| 公司（中/英）| 别克（通用汽车） / Buick / General Motors |
| 产品（中/英）| 免手动电动尾门（带标志投影） / Hands-Free Power Liftgate with logo projection |
| 产品版本 | 标志投影+可编程开启高度版本 |
| 市场 | 通用汽车别克品牌SUV/MPV电动尾门配置；需核查中国在售车型配置表 |
| 上市日期 | 未明确（现有证据仅证明功能存在，未给出首次发布/在华上市时间） |
| 总分（百分制）| 90.0 |
| 权 1 分数 | 90.0 |

**深挖理由**：该配置的核心交互是地面发光Logo指示踢脚位置，用户在保险杠下方踢脚触发电动尾门，直接命中C1-F6的投影图像/脚部检测方向和C1-F5的自动开启控制；中国市场别克车型是否采用同版本需在下游用中文配置表和用户手册确认。

**逐权利要求对比**：

##### 权利要求 1（claim_score: 90.0）

> 1.一种车辆后备箱自动开启控制系统，其特征在于，所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块；
> 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接；
> 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息；
> 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线；
> 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱；
> 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C1-F1 | 所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块 | 别克官方说明中，该功能包含key fob（智能钥匙）、logo projection/踢脚传感器区域（用于指示并检测脚踢）、power liftgate（电动举升门）；诊断功能表还列出无钥匙进入控制模块和举升门控制模块。 | 明确满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Xtooltech](https://www.xtooltech.com/official/pack_pdf/PS_ZGBUICK/PS_ZGBUICK_V16_80_CN.pdf) | 官方页直接披露钥匙、投影/传感器踢脚采集和电动尾门执行；Xtool别克功能表列出无钥匙进入控制模块与举升门控制模块，足以对应三类模块。 |
| C1-F2 | 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接 | 系统在携带key fob接近且脚踢传感器正确触发后控制举升门开启；ACDelco后举升门控制模块说明称其为遥控无钥匙进入的接收器并向车身控制模块传输无钥匙进入命令，支持钥匙模块与尾门/车身控制模块通信。未见本候选的完整线束图。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [SDParts / ACDelco](https://sdparts.com/i-24098312-acdelco-20821156-rear-liftgate-control-module.html)<br>3. [Xtooltech](https://www.xtooltech.com/official/pack_pdf/PS_ZGBUICK/PS_ZGBUICK_V16_80_CN.pdf) | 官方流程显示钥匙接近信息和脚踢传感信息共同用于尾门控制；ACDelco说明和诊断表进一步支持控制模块间通信。但未给出该带Logo投影版本具体线束/电连接图，故保守评为可能满足。 |
| C1-F3 | 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息 | 采集区域位于车辆后部/后保险杠下方：Logo投影在用户接近车辆后方6英尺/1.8米内自动点亮；用户需在保险杠下方踢脚并使脚距保险杠5英寸/12.7厘米内，且钥匙需在车辆3英尺/0.9米内。 | 明确满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 官方页直接给出车辆后部6英尺/1.8米、钥匙3英尺/0.9米、脚距保险杠5英寸/12.7厘米等距离阈值，并要求在后保险杠/尾门下方动作。 |
| C1-F4 | 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线 | 用户需携带key fob接近liftgate；系统要求key fob在车辆3英尺内，并在车尾6英尺内点亮投影。AutoSense资料还要求携带钥匙从10英尺外接近至3英尺内。公开资料未逐字披露“后备箱探测天线”，但存在车尾近距离钥匙探测。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Support](https://www.buick.com/support/quick-start-guides/autosense-liftgate) | key fob对应钥匙侧感应/通信单元；车辆能限定钥匙位于车尾/车身近距离，通常需要后部无钥匙进入接收天线或接收器。因资料未直接披露天线安装于后备箱，评为可能满足。 |
| C1-F5 | 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱 | Power Liftgate在接收正确踢脚/传感器触发后自动打开或关闭；若横扫脚或踩在Logo投影上则“不激活传感器”。Xtool表列出“举升门控制模块”。 | 明确满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Xtooltech](https://www.xtooltech.com/official/pack_pdf/PS_ZGBUICK/PS_ZGBUICK_V16_80_CN.pdf) | 官方页明确正确踢脚动作触发传感器并使举升门开启/关闭，错误动作不触发；诊断表直接列出举升门控制模块，支持后备箱控制单元和启动/执行单元。 |
| C1-F6 | 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向 | 官方页称地面出现illuminated logo projection指示踢脚位置；用户需“kick straight over the logo”或对准旧车sensor，脚距保险杠5英寸/12.7厘米内，并朝车辆下方踢。可推断后保险杠/尾门下方有向地投影与脚踢检测区域，但未直接公开传感器测量“脚部到投影图像”的距离。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 投影到地面、踢过Logo、脚距保险杠5英寸/12.7厘米内和传感器触发均有官方直接证据；但未披露传感器按“脚到投影图像距离”测距，故为可能满足。 |

##### 权利要求 2（claim_score: 30.0）

> 2.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述投影单元为可投射影像的激光投影仪，所述距离检测单元为直线距离传感器。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C2-F1 | 所述投影单元为可投射影像的激光投影仪 | 公开证据仅称为illuminated logo projection/logo lamp，能投射Logo影像到地面；未说明投影单元为“激光投影仪”，也未说明其光源类型。 | 证据不足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | “发光Logo投影/Logo lamp”证明有投影影像，但不能证明是激光投影仪；汽车Logo投影也可能是LED/灯具投影。 |
| C2-F2 | 所述距离检测单元为直线距离传感器 | 公开证据称存在sensor/踢脚传感器，并要求脚踢进入保险杠5英寸/12.7厘米内；未说明传感器类型为直线距离传感器，也未披露其测量直线距离的原理。 | 证据不足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 脚踢传感器可为电容、雷达、红外、超声等多种类型；现有资料没有传感器种类或测距方式，不能证明其为直线距离传感器。 |

##### 权利要求 3（claim_score: 100.0）

> 3.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C3-F1 | 所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启 | 别克系统要求携带key fob并作出正确脚踢动作；设置菜单可启用/关闭Hands-Free Exterior Storage Access；举升门控制模块/后举升门控制模块存在并与无钥匙进入命令通信，最终控制举升门开启。 | 明确满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Support](https://www.buick.com/support/quick-start-guides/autosense-liftgate)<br>3. [SDParts / ACDelco](https://sdparts.com/i-24098312-acdelco-20821156-rear-liftgate-control-module.html) | 官方操作逻辑表明系统同时使用钥匙和脚踢传感信息来决定是否开门；设置菜单和举升门控制模块/车身控制模块证据表明存在电子控制单元执行该判断与控制。 |

##### 权利要求 4（claim_score: 80.0）

> 4.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C4-F1 | 所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱 | 该配置为Power Liftgate/电动举升门，正确脚踢后尾门自动开启/关闭；维修资料显示存在举升门控制模块、锁门总成开关及电动举升门故障诊断。公开资料未直接列出“开启电机”部件位置。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [精通维修下载](http://www.gzweix.com/article/sort0253/sort0254/sort0528/info-332900.html) | “Power Liftgate/电动举升门”通常通过电机/执行器开启尾门，且维修资料证实举升门控制模块控制锁门状态；但未获得本候选型号中开启电机的直接部件或安装位置披露，故为可能满足。 |

##### 权利要求 5（claim_score: 93.33）

> 5.一种车辆后备箱自动开启控制系统的控制方法，所述控制方法应用于权利要求1-4任一项所述的车辆后备箱自动开启控制系统，其特征在于，包括以下步骤：
> 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息；
> 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块；
> 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C5-F1 | 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息 | 用户需携带key fob接近尾门；Logo投影在用户进入车辆后方6英尺/1.8米内自动点亮，钥匙需在车辆3英尺/0.9米内。AutoSense资料还披露必须从10英尺外接近、进入3英尺内才触发开门逻辑。反馈到控制模块属于系统动作推断。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Support](https://www.buick.com/support/quick-start-guides/autosense-liftgate) | “从10英尺外到3英尺内”及“进入车尾6英尺内点亮投影”能证明从远至近的位置状态变化被用于控制；但资料未显示内部信号反馈路径，故为可能满足。 |
| C5-F2 | 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块 | 官方要求脚踢直穿Logo/传感器区域，脚需进入保险杠5英寸/12.7厘米内且不得接触；横扫脚或踩Logo不会激活传感器，表明系统采集脚与后保险杠/尾门区域的距离或接近状态，并用于后续控制。 | 明确满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 5英寸/12.7厘米距离阈值和传感器激活/不激活规则是公开直接证据，足以证明脚与后备箱区域距离状态被采集并作为尾门动作条件。 |
| C5-F3 | 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启 | 当携带key fob并正确脚踢后，尾门在提示灯/蜂鸣后开启；错误踢法不会激活传感器。系统还可通过车辆设置启用/关闭免手动外部储物访问。 | 明确满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Support](https://www.buick.com/support/quick-start-guides/autosense-liftgate) | 官方操作条件同时包括钥匙存在和脚踢传感，满足后自动控制尾门开启，错误动作不触发，直接对应控制模块分析判断后控制开启。 |

##### 权利要求 6（claim_score: 80.0）

> 6.根据权利要求5所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元，
> 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；
> 当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C6-F1 | 步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元 | 别克系统检测key fob接近尾门区域：Logo投影在车尾6英尺/1.8米内点亮，钥匙需在3英尺/0.9米内；AutoSense资料披露从10英尺外接近至3英尺内触发。未直接公开“探测天线”和反馈到ECU的内部路径。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Support](https://www.buick.com/support/quick-start-guides/autosense-liftgate) | 公开资料证明车辆能检测钥匙由远至近进入后部近距离区域；工程上通常由无钥匙进入天线/接收器实现并由控制模块处理。但天线安装位置和ECU反馈信号未直接披露。 |
| C6-F2 | 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；<br>当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2 | AutoSense资料显示，使用前需先远离车辆至少10英尺/约3米超过20秒，再携带钥匙从至少10英尺外接近后部；若钥匙在10英尺范围内停留超过2分钟会被静默，需重新激活。标准Hands-Free页则在钥匙接近后点亮Logo并等待踢脚。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/quick-start-guides/autosense-liftgate)<br>2. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 远离后再接近、否则静默/不响应的逻辑与“无从远至近则重新检测，有则进入脚部检测”高度对应；但公开资料没有给出软件流程图中的返回S1/进入S2语句，因此为可能满足。 |

##### 权利要求 7（claim_score: 80.0）

> 7.根据权利要求6所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C7-F1 | 当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪 | 用户携带key fob接近车尾后，Logo projection会在进入车尾6英尺/1.8米内自动点亮。公开资料未说明该投影为激光投影仪，也未披露ECU发送“脉冲信号”的具体控制方式。 | 可能满足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 钥匙接近后自动开启地面Logo投影与本特征的外部功能一致；但“脉冲信号”和“激光投影仪”均为内部实现/器件类型，现有证据未直接证明，故仅可推断为可能满足。 |

##### 权利要求 8（claim_score: 30.0）

> 8.根据权利要求7所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n)，设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C8-F1 | 步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n) | 现有证据仅证明地面有Logo投影，且用户需踢过Logo/传感器区域；未证明投影仪为激光，未证明存在直线距离传感器实时测量“传感器到投影影像”的D值序列并反馈给电控单元。 | 证据不足 | [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 官方资料披露的是用户交互层面的投影位置与脚踢动作，没有公开D、D1...Dn实时测距数据、传感器到投影影像距离或反馈算法。 |
| C8-F2 | 设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di | 现有公开资料没有关于投射距离基准值C、D值最大值Di、以及C=Di算法设定的披露。 | 证据不足 | [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 资料甚至强调Logo投影主要用于定位踢脚位置，未披露以投射距离最大值作为基准值的控制算法，因此证据不足。 |

##### 权利要求 9（claim_score: 30.0）

> 9.根据权利要求8所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C9-F1 | 步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上 | 官方资料称横扫脚或踩在Logo投影上不会激活传感器，并要求踢脚在1秒内完成；未披露C、D、C-D≤1cm阈值，也未披露据此判断人脚未放到影像上的算法。 | 证据不足 | [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | “踩Logo不激活”与该特征的结论存在部分相似，但缺少直线距离传感器、C-D≤1cm和人脚未放置判断的公开算法细节，不能认定满足。 |

##### 权利要求 10（claim_score: 30.0）

> 10.根据权利要求9所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C10-F1 | 当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像 | 官方Q&A提到如果没有及时踢脚，Logo lamp/projection会熄灭；但未披露该熄灭由C-D≤1cm持续t1秒触发，也未证明投影单元为激光投影仪。 | 证据不足 | 1. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | Logo灯存在自动熄灭现象，但触发条件和专利限定的C-D≤1cm、持续t1秒之间没有公开对应关系，证据不足。 |

##### 权利要求 11（claim_score: 30.0）

> 11.根据权利要求9或10所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3，还包括以下步骤：
> 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上；
> 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C11-F1 | 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上 | 公开证据仅披露脚应踢过Logo/传感器区域、脚距保险杠5英寸/12.7厘米内，未披露C-D大于1cm且小于8cm这一阈值，也未披露判断“人脚落在地面的影像上”的算法。 | 证据不足 | [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | 5英寸/12.7厘米是脚与保险杠的接近要求，不等于专利的C-D 1-8cm区间；缺少内部测距变量和阈值。 |
| C11-F2 | 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测 | 公开证据没有C-D≥8cm阈值或返回S1重新检测的算法。AutoSense资料仅说明远离/接近和静默/重新激活条件。 | 证据不足 | [Buick Support](https://www.buick.com/support/quick-start-guides/autosense-liftgate) | 重新激活流程可说明系统有重复检测逻辑，但不能证明C-D≥8cm时返回S1这一具体判据。 |

##### 权利要求 12（claim_score: 30.0）

> 12.根据权利要求11所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，
> 如果是，所述电控单元控制开启后备箱；
> 否则，返回S1进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C12-F1 | 当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，<br>如果是，所述电控单元控制开启后备箱；<br>否则，返回S1进行重新检测 | 官方资料显示正确脚踢后尾灯闪烁并有chime提示，尾门在给用户退开时间后开启；关闭时也有2秒延迟。资料未披露脚落在影像上后的蜂鸣器提示时序、C-D 1-8cm持续t2秒判断，或否则返回S1的算法。 | 证据不足 | 1. [Buick Support](https://www.buick.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>2. [Buick Canada](https://www.buick.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate) | Chime/蜂鸣提示和延迟开启有直接证据，但该特征核心是C-D 1-8cm持续t2秒后开门、否则返回S1；这些内部阈值与流程未公开，故证据不足。 |

#### 该候选的证据缺口（如有）

- 权1 C1-F2（可能满足）：建议下一步人工搜索。
- 权1 C1-F4（可能满足）：建议下一步人工搜索。
- 权1 C1-F6（可能满足）：建议下一步人工搜索。
- 权2 C2-F1（证据不足）：建议下一步人工搜索。
- 权2 C2-F2（证据不足）：建议下一步人工搜索。
- 权4 C4-F1（可能满足）：建议下一步人工搜索。
- 权5 C5-F1（可能满足）：建议下一步人工搜索。
- 权6 C6-F1（可能满足）：建议下一步人工搜索。
- 权6 C6-F2（可能满足）：建议下一步人工搜索。
- 权7 C7-F1（可能满足）：建议下一步人工搜索。
- 权8 C8-F1（证据不足）：建议下一步人工搜索。
- 权8 C8-F2（证据不足）：建议下一步人工搜索。
- 权9 C9-F1（证据不足）：建议下一步人工搜索。
- 权10 C10-F1（证据不足）：建议下一步人工搜索。
- 权11 C11-F1（证据不足）：建议下一步人工搜索。
- 权11 C11-F2（证据不足）：建议下一步人工搜索。
- 权12 C12-F1（证据不足）：建议下一步人工搜索。

#### TOP4: 佛山市安驾科技有限公司 汽车尾门AR光感脚踢传感器 KS32；汽车后备箱投影灯感应开关加装款

| 字段 | 值 |
|---|---|
| 候选 ID | P03 |
| 公司（中/英）| 佛山市安驾科技有限公司 / Foshan Anjia Technology Co., Ltd. |
| 产品（中/英）| 汽车尾门AR光感脚踢传感器 / AR light-sensing kick sensor for automotive tailgate |
| 产品版本 | KS32；汽车后备箱投影灯感应开关加装款 |
| 市场 | 中国汽车电动尾门后装/改装配件市场 |
| 上市日期 | 未明确；已见2024年8月1688在售/页面记录 |
| 总分（百分制）| 80.0 |
| 权 1 分数 | 80.0 |

**深挖理由**：该1688商品明确同时具备“AR光感脚踢传感器”和“后备箱投影灯感应开关”，形态上接近C1-F6的投影图像+脚部检测；若其控制器与电动尾门/智能钥匙联动，则可能进一步覆盖C1-F1至C1-F5，适合下游围绕KS32规格书、安装说明、控制逻辑深挖。

**逐权利要求对比**：

##### 权利要求 1（claim_score: 80.0）

> 1.一种车辆后备箱自动开启控制系统，其特征在于，所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块；
> 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接；
> 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息；
> 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线；
> 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱；
> 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C1-F1 | 所述系统包括：信息采集模块、智能钥匙模块以及后备箱控制模块 | KS32页面显示其为“汽车尾门AR光感脚踢传感器/后备箱投影灯感应开关”；安驾技术摘要称其光感脚踢方案通过智能电动尾门模块与原车BCM、KESSY协议协同工作，利用微波/毫米波感应携带智能钥匙的用户，并通过光学投影显示。可对应信息采集模块、智能钥匙模块和后备箱控制模块三类功能模块，但未见KS32专属系统框图。 | 可能满足 | 1. [1688/阿里巴巴](https://detail.1688.com/offer/821120630933.html)<br>2. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>3. [搜狐汽车](https://www.sohu.com/a/785936895_121630056) | 1688确认KS32是后备箱/尾门AR光感脚踢投影感应产品；CSDN摘要关联电动尾门模块、BCM、KESSY、感应及光学投影。缺少KS32官方电气框图，故为可能满足。 |
| C1-F2 | 所述信息采集模块、所述智能钥匙模块均与后备箱控制模块电连接 | 安驾摘要称感应/投影方案与智能电动尾门模块、原车BCM、KESSY协议协同；同类脚踢传感器公开有硬线输出、LIN总线输出。补搜的通用一脚踢安装资料还显示传感器通过红/黑电源线、绿色触发线、ACC线等接入电尾门/尾箱保险盒链路。可推断KS32信息采集模块与尾门控制链路电连接，智能钥匙模块通过KESSY/BCM参与控制，但未见KS32专属接线图。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [我爱方案网](http://www.52solution.com/facs/7814)<br>3. [车主手册/icauto](https://www.icauto.com.cn/baike/69/696565.html) | “协同工作”、硬线/LIN输出和一脚踢安装线束资料均支持传感器、钥匙授权系统与尾门控制器之间存在电信号连接；但未取得KS32端口定义或接线图，故不是明确满足。 |
| C1-F3 | 所述信息采集模块设置在车辆后备箱并用于获取用户与车辆后备箱的距离信息 | KS32商品名直接指向“汽车尾门/后备箱”脚踢传感器；安驾摘要称利用微波/毫米波感应携带智能钥匙的用户；同类尾箱脚踢开关网页说明微波感应模块位于汽车尾部，用于探测人体脚部动作，检测距离约30cm。KS32自身未公开具体“距离信息”参数。 | 可能满足 | 1. [1688/阿里巴巴](https://detail.1688.com/offer/821120630933.html)<br>2. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>3. [蓝水花智能电子](http://www.lshzn.cn/product/27.html) | 产品用途、安装部位和感应原理均指向在车尾/后备箱区域采集用户脚部或用户接近信息；微波/毫米波感应通常包含目标接近/距离或距离阈值判断。但KS32未公开可量化距离参数，故为可能满足。 |
| C1-F4 | 所述智能钥匙模块包括设置在车辆钥匙中的钥匙感应单元，以及设置在车辆后备箱并可探测到所述钥匙感应单元的探测天线 | 安驾摘要称方案与原车KESSY协议协同并感应携带智能钥匙的用户；KESSY资料显示无钥匙系统可通过低频天线向钥匙发送认证请求，并存在后保险杠支架处天线、行李箱上部天线等后部天线。行业资料也称需携带匹配钥匙到后备箱处才能开启。KS32未直接公开其使用的后部探测天线型号或位置。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [库贝汽车网](https://www.kb9.cn/read/38022.html)<br>3. [搜狐汽车](https://www.sohu.com/a/785936895_121630056) | 安驾方案明确与KESSY协同；KESSY公开资料能够解释车辆钥匙感应单元与后保险杠/行李箱天线的技术链路。由于证据不是KS32自身说明书，故只能认定可能满足。 |
| C1-F5 | 后备箱控制模块包括后备箱启动单元和后备箱控制单元，所述后备箱控制单元根据所述信息采集模块提供的信息可判断是否启动所述后备箱启动单元开启后备箱 | 安驾摘要称其与智能电动尾门模块、BCM/KESSY协同；同类资料称脚踢传感器感应脚踢动作后通过ECU向尾门电动撑杆和自吸锁发出指令，或输出电平信号控制后备箱开启/关闭。可对应控制单元判断信息采集模块输入并驱动尾门启动部件；KS32控制器内部单元划分未公开。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [蓝水花智能电子](http://www.lshzn.cn/product/27.html)<br>3. [搜狐汽车](https://www.sohu.com/a/785936895_121630056) | 公开资料支持“传感器检测—ECU/尾门模块判断—电动撑杆/锁具动作”的控制链路。KS32没有公开启动单元和控制单元的模块化结构，因此保持可能满足。 |
| C1-F6 | 所述信息采集模块包括投射图像的投影单元，以及可测量脚部到投影图像距离的距离检测单元，所述投影单元和所述距离检测单元均设置在车辆后备箱的下方且指向地面方向 | KS32商品名含“AR光感脚踢传感器”和“后备箱投影灯感应开关”；安驾摘要称有光学投影和微波/毫米波感应。公开AR智能投影尾门技术显示：车辆在车尾地面投射logo，脚踩投影时由TOF模组检测并发出指令，投影距车尾约390-400mm。KS32未直接公开TOF/测距方式及投影、传感单元均位于后备箱下方朝地。 | 可能满足 | 1. [1688/阿里巴巴](https://detail.1688.com/offer/821120630933.html)<br>2. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>3. [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html)<br>4. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | KS32直接声称投影灯+脚踢/光感；安驾摘要确认光学投影及感应；同类AR投影尾门采用车尾地面投影和TOF检测脚踩。缺口在于KS32未公开测距传感器和安装朝向。 |

##### 权利要求 2（claim_score: 55.0）

> 2.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述投影单元为可投射影像的激光投影仪，所述距离检测单元为直线距离传感器。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C2-F1 | 所述投影单元为可投射影像的激光投影仪 | KS32公开页面仅称“后备箱投影灯”“AR光感”；安驾摘要称“光学投影”；同类AR尾门资料称“MLA光学投影技术”。现有证据未说明KS32使用激光投影仪，也未说明投影光源为激光。 | 证据不足 | 1. [1688/阿里巴巴](https://detail.1688.com/offer/821120630933.html)<br>2. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>3. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | “投影灯/光学投影/MLA投影”可证明存在投影功能，但不能证明其是“激光投影仪”。也没有相反证据证明不是激光，因此不判明确不满足，仅判证据不足。 |
| C2-F2 | 所述距离检测单元为直线距离传感器 | 安驾摘要称KS32相关方案使用微波/毫米波感应；同类AR智能尾门公开用TOF模组检测脚踩投影并发出指令。TOF本质上可进行直线距离测量，微波/毫米波感应也常用于距离/接近判断，但KS32未公开其距离检测单元的具体类型。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html)<br>3. [蓝水花智能电子](http://www.lshzn.cn/product/27.html) | TOF模组和微波/毫米波模块均可用于距离或接近检测；结合AR投影脚踢场景，可以合理推断存在直线距离/接近检测能力。但KS32没有传感器型号或测距输出定义，故为可能满足。 |

##### 权利要求 3（claim_score: 80.0）

> 3.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C3-F1 | 所述后备箱控制模块还包括电控单元，所述电控单元用于接收判断所述信息采集模块和所述智能钥匙模块提供的信息，并控制后备箱的开启 | 安驾摘要称其方案通过智能电动尾门模块与BCM、KESSY协议协同；行业资料称脚踢传感器感应脚踢动作后通过ECU向尾门电动撑杆和自吸锁发出指令。BCM资料显示车身控制模块可处理传感器/开关信号并控制电动尾门等车身电器。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [搜狐汽车](https://www.sohu.com/a/785936895_121630056)<br>3. [腾讯新闻/Tavily摘要](https://news.qq.com/rain/a/20240603A09GMF00) | CSDN的安驾资料和行业资料均支持存在接收脚踢感应、钥匙授权并控制尾门的ECU/BCM/电动尾门模块。但未见KS32控制器软件逻辑或ECU名称，故为可能满足。 |

##### 权利要求 4（claim_score: 80.0）

> 4.根据权利要求1所述的车辆后备箱自动开启控制系统，其特征在于，所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C4-F1 | 所述后备箱控制模块还包括开启电机，所述开启电机安装在车辆后备箱且用于开启车辆后备箱 | KS32自身公开为后备箱投影灯感应开关/脚踢传感器，通常作为电动尾门加装系统的输入部件；安驾摘要称其与智能电动尾门模块协同；行业资料说明脚踢传感器通过ECU向尾门电动撑杆和尾门自吸锁发出指令，执行自动开关。可对应安装在尾门/后备箱区域的开启电机或电动撑杆，但KS32页面未说明其套装包含电机。 | 可能满足 | 1. [1688/阿里巴巴](https://detail.1688.com/offer/821120630933.html)<br>2. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>3. [搜狐汽车](https://www.sohu.com/a/785936895_121630056) | “智能电动尾门模块”和“电动撑杆/自吸锁”可对应尾门开启执行机构。由于KS32商品本身更像传感器/开关而非完整电尾门套装，且未公开电机安装信息，故只能可能满足。 |

##### 权利要求 5（claim_score: 80.0）

> 5.一种车辆后备箱自动开启控制系统的控制方法，所述控制方法应用于权利要求1-4任一项所述的车辆后备箱自动开启控制系统，其特征在于，包括以下步骤：
> 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息；
> 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块；
> 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C5-F1 | 步骤S1：所述智能钥匙模块将检测到的所述智能钥匙的位置变化信息反馈到所述后备箱控制模块，所述位置变化信息为所述智能钥匙从远至近的位置状态变化信息 | 安驾摘要称方案与原车KESSY协议协同并感应携带智能钥匙的用户；行业资料称携带匹配钥匙走到后备箱处可触发脚踢开启；KESSY资料显示系统会在车辆附近搜索合法钥匙。可对应智能钥匙从远至近进入车尾接近范围并反馈给尾门/BCM控制链路，但未见KS32公开“位置变化信息”变量。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [搜狐汽车](https://www.sohu.com/a/785936895_121630056)<br>3. [汽车之家](https://www.autohome.com.cn/ask/9381810.html) | 钥匙进入后备箱附近后进行KESSY认证是该类系统正常工作前提；可推断有钥匙接近/存在信息进入尾门控制逻辑。精确的“从远至近的位置状态变化信息”没有KS32专属公开，故为可能满足。 |
| C5-F2 | 步骤S2：所述信息采集模块采集人脚与后备箱的距离状态信息，并将所述状态信息反馈到所述后备箱控制模块 | KS32为后备箱AR光感脚踢传感器；安驾摘要称使用微波/毫米波感应并光学投影；同类尾箱脚踢产品公开检测距离约30cm；AR投影尾门资料称脚踩投影时TOF模组检测并发出指令。可对应采集脚部相对后备箱/投影区域的距离或接近状态并反馈控制模块。 | 可能满足 | 1. [1688/阿里巴巴](https://detail.1688.com/offer/821120630933.html)<br>2. [蓝水花智能电子](http://www.lshzn.cn/product/27.html)<br>3. [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html) | 公开资料支持脚部检测和距离/接近检测的功能链路，但KS32未公开距离状态信息格式或反馈接口，因此为可能满足。 |
| C5-F3 | 步骤S3：所述后备箱控制模块对所述智能钥匙模块和所述信息采集模块传递来的信息进行分析判断，控制后备箱的开启 | 安驾摘要称与智能电动尾门模块、BCM、KESSY协同；行业资料称脚踢传感器感应脚踢动作后通过ECU向电动撑杆和自吸锁发出指令；通用安装资料称红正极接入后触碰绿色线和黑色线可使尾门开关。可对应对钥匙授权和脚踢/感应信号进行分析后控制开启。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [搜狐汽车](https://www.sohu.com/a/785936895_121630056)<br>3. [KMAutospace/Tavily摘要](https://kmautospace.com/info-detail/foot-sensor-installation) | 尾门控制模块/ECU根据脚踢感应与钥匙授权条件执行尾门开启是该类产品公开工作链路；KS32未披露完整判断流程，故为可能满足。 |

##### 权利要求 6（claim_score: 55.0）

> 6.根据权利要求5所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元，
> 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；
> 当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C6-F1 | 步骤S1具体为:所述探测天线探测设置在钥匙中的所述钥匙感应单元是否存在从远至近的位置状态变化的位置变化信息，并将探测到位置变化信息反馈到所述后备箱控制模块的电控单元 | 安驾摘要称与KESSY协议协同并感应携带智能钥匙的用户；KESSY资料显示车辆可通过后保险杠支架处天线、行李箱上部天线等搜索合法钥匙并与钥匙转发器交互。可对应探测天线探测钥匙感应单元并向BCM/尾门控制链路反馈，但KS32未公开专属天线位置或“从远至近”状态量。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [库贝汽车网](https://www.kb9.cn/read/38022.html)<br>3. [精通维修下载/Exa摘要](http://www.gzweix.com/article/sort0253/sort0487/info-262655.html) | KESSY后部天线与钥匙感应/认证链路为公开常规结构；安驾方案明确与KESSY协同。缺少KS32自身对“探测天线—电控单元—位置变化信息”的披露，故为可能满足。 |
| C6-F2 | 当所述电控单元判断所述钥匙感应单元不存在从远至近的位置变化时，返回重新检测；<br>当所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，进入步骤S2 | 现有证据显示同类系统要求携带匹配钥匙走到后备箱处，并在钥匙授权/感应后允许脚踢开启；但没有公开KS32或安驾方案在钥匙不存在时“返回重新检测”、在钥匙从远至近变化存在时“进入S2”的程序分支。 | 证据不足 | 1. [搜狐汽车](https://www.sohu.com/a/785936895_121630056)<br>2. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | 证据能支持“钥匙在车尾附近后系统才工作”的大方向，但不能证明权利要求限定的循环检测/分支跳转流程。没有矛盾证据，故为证据不足。 |

##### 权利要求 7（claim_score: 80.0）

> 7.根据权利要求6所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C7-F1 | 当由所述电控单元判断所述钥匙感应单元存在从远至近的位置变化时，则所述电控单元发送脉冲信号开启所述信息采集模块中的激光投影仪 | 安驾摘要称与KESSY协同并通过光学投影显示；同类AR投影尾门资料称当车主带钥匙到达车尾部时车辆自动感知，并通过MLA光学投影在地面投射logo。可对应钥匙接近后控制投影开启，但现有证据未公开“脉冲信号”，也未证明投影单元为“激光投影仪”。 | 可能满足 | 1. [CSDN](https://blog.csdn.net/weixin_53077062/article/details/140233400)<br>2. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | “带钥匙到车尾—车辆自动感知—地面投影开启”的公开流程与本特征核心顺序相符；但“脉冲信号”和“激光投影仪”是更细的硬件/电控限定，未被直接公开。 |

##### 权利要求 8（claim_score: 55.0）

> 8.根据权利要求7所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n)，设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C8-F1 | 步骤S2：所述激光投影仪将影像投射到地面，所述信息采集模块中的直线距离传感器实时检测所述直线距离传感器到所述影像的投射实际距离为D，并将D反馈到所述电控单元，所述检测到的D值为D1，D2……Di……Dn(i、n为自然数，且i<n) | KS32公开为后备箱投影灯感应开关；安驾摘要称光学投影和微波/毫米波感应；同类AR尾门资料称MLA光学投影在地面投射图案，用户脚踩后由TOF模组检测并发出指令。TOF/测距模组可产生随时间变化的距离读数D1...Dn，但证据未公开KS32实时记录D序列或投影实际距离变量D。 | 可能满足 | 1. [1688/阿里巴巴](https://detail.1688.com/offer/821120630933.html)<br>2. [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html)<br>3. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | 地面投影与TOF检测资料可支持“投影+距离检测+向控制端发出指令”的技术推断；连续距离值D1...Dn属于TOF/测距工作方式的合理推论。但KS32未公开变量及激光属性。 |
| C8-F2 | 设定投射距离基准值为C，设投射实际距离的最大值为Di，则C＝Di | 现有KS32、安驾摘要及同类AR尾门公开资料均未披露设定投射距离基准值C，也未披露以实时距离最大值Di作为基准值C的算法。 | 证据不足 | 1. [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html)<br>2. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | 证据仅显示有TOF检测和投影距离示例，没有任何C、D、最大值Di或C=Di的控制算法披露。因此证据不足。 |

##### 权利要求 9（claim_score: 30.0）

> 9.根据权利要求8所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C9-F1 | 步骤S3：当所述直线距离传感器检测到C与D的差值小于等于1cm，则所述电控单元判断人脚没有放置到地面的影像上 | 现有证据仅显示AR投影尾门可在车尾地面投射图案并由TOF模组检测脚踩，未公开KS32或安驾方案采用C-D≤1cm作为“脚未放置在影像上”的判断阈值。 | 证据不足 | [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html) | 没有公开C、D差值阈值或1cm判定条件，无法证明该从属方法步骤。 |

##### 权利要求 10（claim_score: 30.0）

> 10.根据权利要求9所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C10-F1 | 当C与D的差值小于等于1cm，且所述电控单元判断该状态持续时间是大于等于预设的t1秒，则所述电控单元控制所述激光投影仪熄灭影像 | 现有公开资料未披露KS32或安驾方案在C-D≤1cm并持续t1秒后关闭投影图像；也未披露t1秒设定或投影熄灭控制逻辑。 | 证据不足 | [砍柴网](https://m.ikanchai.com/pcarticle/437409) | 资料仅显示投影和TOF检测，没有C-D≤1cm、持续时间t1、投影熄灭条件的任何公开内容，故证据不足。 |

##### 权利要求 11（claim_score: 30.0）

> 11.根据权利要求9或10所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，步骤S3，还包括以下步骤：
> 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上；
> 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C11-F1 | 当所述直线距离传感器检测到C与D的差值大于1cm，且小于8cm，则所述电控单元判断人脚落在地面的影像上 | 同类AR投影尾门资料称脚踩地面投影后TOF模组准确检测并发出指令，但没有公开以C-D大于1cm且小于8cm作为“人脚落在影像上”的判断区间。 | 证据不足 | 1. [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html)<br>2. [砍柴网](https://m.ikanchai.com/pcarticle/437409) | 有脚踩投影检测的概念证据，但没有1cm-8cm阈值区间证据，故证据不足。 |
| C11-F2 | 当判断所述C与D的差值大于等于8cm，返回S1步骤进行重新检测 | 未见KS32、安驾方案或同类AR尾门资料公开C-D≥8cm时返回钥匙检测步骤S1的控制流程。 | 证据不足 | [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html) | 没有8cm阈值和返回S1重新检测的公开算法。 |

##### 权利要求 12（claim_score: 30.0）

> 12.根据权利要求11所述的车辆后备箱自动开启控制系统的控制方法，其特征在于，当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，
> 如果是，所述电控单元控制开启后备箱；
> 否则，返回S1进行重新检测。

| feature_id | 权利要求技术特征 | 竞品对应特征 | 状态 | 证据 URL | 说明 |
|---|---|---|---|---|---|
| C12-F1 | 当所述电控单元判断人脚落在地面的影像上时，则蜂鸣器发出提示，进一步判断所述C与D的差值大于1cm且小于8cm的状态的持续时间是否大于等于t2秒时，<br>如果是，所述电控单元控制开启后备箱；<br>否则，返回S1进行重新检测 | 现有资料显示脚踩/脚踢被传感器或TOF模组检测后可控制尾门开启；但没有公开KS32或安驾方案具备蜂鸣器提示，也没有公开1cm-8cm状态持续t2秒、满足则开启、不满足返回S1的完整逻辑。 | 证据不足 | 1. [搜狐汽车](https://www.sohu.com/a/785936895_121630056)<br>2. [深圳都市网](https://www.citysz.net/qiche/2021/0317/202121383.html) | 资料只能证明检测后开启尾门的大方向；蜂鸣器、t2持续时间、1cm-8cm区间以及返回S1流程均无公开证据，故证据不足。 |

#### 该候选的证据缺口（如有）

- 权1 C1-F1（可能满足）：建议下一步人工搜索。
- 权1 C1-F2（可能满足）：建议下一步人工搜索。
- 权1 C1-F3（可能满足）：建议下一步人工搜索。
- 权1 C1-F4（可能满足）：建议下一步人工搜索。
- 权1 C1-F5（可能满足）：建议下一步人工搜索。
- 权1 C1-F6（可能满足）：建议下一步人工搜索。
- 权2 C2-F1（证据不足）：建议下一步人工搜索。
- 权2 C2-F2（可能满足）：建议下一步人工搜索。
- 权3 C3-F1（可能满足）：建议下一步人工搜索。
- 权4 C4-F1（可能满足）：建议下一步人工搜索。
- 权5 C5-F1（可能满足）：建议下一步人工搜索。
- 权5 C5-F2（可能满足）：建议下一步人工搜索。
- 权5 C5-F3（可能满足）：建议下一步人工搜索。
- 权6 C6-F1（可能满足）：建议下一步人工搜索。
- 权6 C6-F2（证据不足）：建议下一步人工搜索。
- 权7 C7-F1（可能满足）：建议下一步人工搜索。
- 权8 C8-F1（可能满足）：建议下一步人工搜索。
- 权8 C8-F2（证据不足）：建议下一步人工搜索。
- 权9 C9-F1（证据不足）：建议下一步人工搜索。
- 权10 C10-F1（证据不足）：建议下一步人工搜索。
- 权11 C11-F1（证据不足）：建议下一步人工搜索。
- 权11 C11-F2（证据不足）：建议下一步人工搜索。
- 权12 C12-F1（证据不足）：建议下一步人工搜索。

## 4. 下一步建议

- 重点补查权利要求1中的 C1-F2、C1-F4、C1-F6：P02 的 C1-F2、C1-F4仍为“可能满足”，应优先获取 ASU AR智能投影尾门开关的安装手册、线束图、控制器接口定义、后部钥匙天线或蓝牙钥匙接收模块资料；P06/P05 的 C1-F6 需区分“脚部到投影图像距离检测”与“保险杠下方踢脚传感”两种原理。
- 从属权利要求中争议最大的是权6-12，尤其是权7的“脉冲信号”、权8的 D/D1...Dn 与 C＝Di 算法、权9-12的 1cm/8cm/t1/t2 阈值和返回S1流程。上述内容通常不在宣传页披露，应通过拆机、软件标定资料、服务手册、诊断报文、供应商技术白皮书或样品测试补强。
- 对 P02 应立即考虑证据保全：保全一数科技官网页面、新闻稿、汽车之家/新浪/砍柴网等公开页面，优先使用 web archive、公证网页取证，并尽可能购买或取得搭载样车/样件进行功能录像、安装位置拍摄和接口记录。
- 最值得继续深挖的候选为 P02、P06、P05、P03。其中 P02 与权1核心结构重合度最高；P06/P05为同一集团相近功能配置，应重点核对中国销售车型及具体控制原理；P03虽总分 80.0，但公开资料偏商品页和二手摘要，若能取得 KS32说明书、接线图及实物，证据提升空间较大。
- 失格候选 P04 的失格理由集中在权1 C1-F6“投影图像距离检测”被 GM/NHTSA 公开资料反向否定；建议二次复核同集团 Chevrolet/GMC/Cadillac/Buick 是否完全采用同一后保险杠天线方案，避免将 Chevrolet 的否定证据机械外推至 Cadillac/Buick 具体车型。已触发相似专利核查，建议同步比对同申请人同主题的延续案/分案。

## 5. 失格候选附录

| candidate_id | 公司 | 产品 | 失格原因 | 失格相关证据 URL |
|---|---|---|---|---|
| P04 | 雪佛兰（通用汽车） | 免手动电动尾门（带标志投影） | 权利要求1的C1-F6明确不满足：新增GM/NHTSA公开证据显示，GM该功能的脚部检测由后保险杠饰板内“两根天线”触发，脚和小腿需接近后饰板约6.5英寸/16.5cm；同时GMC Canada页面明确称logo投影只帮助找到踢脚位置，不影响免手动尾门控制。这与权1要求“距离检测单元测量脚部到投影图像距离，且投影单元和距离检测单元均设置在后备箱下方并指向地面方向”的结构/检测原理直接相矛盾。未因上市日期失格。 | 1. [NHTSA / General Motors](https://static.nhtsa.gov/odi/tsbs/2019/MC-10160086-9999.pdf)<br>2. [GMC Canada](https://www.gmccanada.ca/en/support/vehicle/storage-doors-windows/hands-free-power-liftgate)<br>3. [GMC](https://www.gmc.com/support/vehicle/storage-doors-windows/hands-free-power-liftgate) |

## 6. 相似专利人工核查

本专利已发现 ≥ 80 分竞品，存在被侵权风险。基于同申请人同主题原则，本专利的同族延续案/分案极可能面临同样侵权风险，建议人工通过下方 Google Patents 高级检索链接核查（链接已按 CN / BYD Co Ltd / 一种车辆后备箱自动开启系统及其控制方法 预先过滤）。

| 项 | 值 |
|---|---|
| 国家代码 | CN |
| 申请人 | BYD Co Ltd |
| 标题 | 一种车辆后备箱自动开启系统及其控制方法 |
| 触发分数 | 93.33（阈值 80.0） |

[在 Google Patents 高级检索中打开](https://patents.google.com/?q=%22%E4%B8%80%E7%A7%8D%E8%BD%A6%E8%BE%86%E5%90%8E%E5%A4%87%E7%AE%B1%E8%87%AA%E5%8A%A8%E5%BC%80%E5%90%AF%E7%B3%BB%E7%BB%9F%E5%8F%8A%E5%85%B6%E6%8E%A7%E5%88%B6%E6%96%B9%E6%B3%95%22&assignee=BYD+Co+Ltd&country=CN&dups=language)

链接已经把 Duplicates 预设为 `Publication number`（即不按 family 去重），页面打开后直接就能看到同族下所有同名公开号。
