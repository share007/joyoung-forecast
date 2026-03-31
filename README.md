# 产销预测模块提取说明

本目录从原项目中提取了“产销预测系统”相关核心代码，便于独立查看、迁移或二次开发。

## 2026-03 实施进展（第一批）

已开始按“导入标准化 + 预测模型竞赛 + 产销建议闭环”实施，当前已落地：

1. 后端服务层拆分（`backend/services`）
2. Excel/CSV 规范化解析（支持多工作表自动识别）
3. Champion-Challenger 预测机制（LightGBM + 基线模型自动择优）
4. 产销建议接口（生产量、补货量、安全库存、风险等级）
5. 导入批次与计划结果落库（可追溯）

## 目录结构

- frontend/app/home/forecast/dashboard/page.tsx  
  产销预测前端页面（截图对应页面）
- frontend/app/layout.tsx
  Next.js 应用布局与字体配置
- frontend/app/globals.css
  九阳主题色与全局样式变量
- frontend/.env.local.example
  前端环境变量示例
- backend/main.py  
  FastAPI 接口（产品列表、销售数据、上传、预测）
- backend/database.py  
  SQLite 数据访问层
- backend/requirements.txt  
  后端 Python 依赖
- backend/data/sample_sales_data.csv  
  示例数据

## 前端调用的后端接口

前端文件中 API_BASE 固定为：http://localhost:8000

- GET /products
- GET /products/{product_name}/sales
- POST /upload
- POST /products/{product_name}/data
- POST /forecast

## 新增接口（第一批实现）

- GET /products/{product_name}/imports
  - 查询最近导入批次（文件名、sheet、导入条数、状态、时间）
- POST /planning/recommendation
  - 输入产品与计划参数，输出预测与产销建议
  - 关键参数示例：
    - `forecast_days`: 预测天数
    - `in_transit`: 在途库存
    - `lead_time_days`: 交付提前期
    - `service_level`: 服务水平（如 0.95）
    - `moq`: 最小起订量
    - `pack_size`: 包装倍数

### `/planning/recommendation` 请求示例

```json
{
  "product_name": "破壁机",
  "forecast_days": 30,
  "in_transit": 120,
  "lead_time_days": 10,
  "service_level": 0.95,
  "moq": 50,
  "pack_size": 10
}
```

### `/planning/recommendation` 返回重点字段

- `forecast.predictions`: 未来逐日需求预测
- `forecast.metrics.method`: 被选中的冠军模型
- `recommendation.production_recommendation`: 建议生产量
- `recommendation.replenishment_recommendation`: 建议补货量
- `recommendation.safety_stock`: 安全库存
- `recommendation.stock_cover_days`: 库存覆盖天数
- `recommendation.risk_level`: 缺货风险等级

## 你截图中 Failed to fetch 的原因

页面报错“Failed to fetch”通常表示前端无法连接到后端地址 http://localhost:8000，常见原因：

1. 后端服务未启动
2. 后端启动端口不是 8000
3. 本机防火墙或代理拦截
4. 后端依赖未安装导致服务启动失败

## 后端启动方式（在原项目中）

1. 进入 backend 目录
2. 安装依赖：pip install -r requirements.txt
3. 启动服务：python main.py

服务启动后，访问 http://localhost:8000/ 应返回运行信息。

## 前端启动方式（已补齐骨架）

1. 进入 frontend 目录
2. 安装依赖：npm install
3. 复制环境变量：cp .env.local.example .env.local
4. 启动前端：npm run dev

启动后访问 http://localhost:3000。

### 主题说明

前端已切换为九阳品牌风格，主色采用橙金体系：

- 主色：`#F39800`
- 深主色：`#DC7F00`
- 强调色：`#FF5A1F`
- 背景基调：暖白与浅橙渐变

## 说明

这里是“代码提取版”，用于模块归档和快速迁移。若要完全独立运行前端，还需要补齐 Next.js 工程骨架（如 package.json、next.config、app/layout.tsx、全局样式等）。
