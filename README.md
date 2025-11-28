# ETF 持仓抓取工具

一个用于抓取中国市场 ETF 最新披露股票持仓信息的 Python 工具。

## 功能特性

- 从东方财富网获取 ETF 持仓数据
- 支持按季度查询持仓信息
- 自动保存股票代码列表（含/不含股票名称）
- 支持自定义最少持仓数量要求

## 环境要求

- Python 3.6+
- 依赖库：
  - requests
  - beautifulsoup4

## 安装依赖

```bash
pip install requests beautifulsoup4
```

## 使用方法

### 基本用法

```bash
python3 fetch_etf_holdings.py <ETF代码>
```

例如：
```bash
python3 fetch_etf_holdings.py 562590
```

### 高级选项

```bash
# 列出所有可用季度及持仓数量
python3 fetch_etf_holdings.py 512170 --list-quarters

# 指定最少持仓数量要求（默认20）
python3 fetch_etf_holdings.py 512170 --min-count 50

# 指定优先选择的季度
python3 fetch_etf_holdings.py 512170 --quarter "2025年2季度"
```

## 输出说明

脚本会生成两个文件：

1. `<ETF代码>_<基金名称>.txt` - 仅包含股票代码（空格分隔）
2. `<ETF代码>_<基金名称>_with_names.txt` - 包含股票代码和名称（格式：`代码:名称`）

同时，股票代码列表会输出到标准输出（每行一个）。

## 注意事项

- ETF 代码必须是6位数字
- 数据来源于东方财富网公开披露信息
- 网络请求设置了10秒超时
- 自动去重，保持披露顺序

## 示例

```bash
$ python3 fetch_etf_holdings.py 512170
结果已保存到 512170_医疗ETF.txt
结果已保存到 512170_医疗ETF_with_names.txt
600276
300003
300015
...
```

## 许可证

本项目仅供学习交流使用。

