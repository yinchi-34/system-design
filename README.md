# System Design 练习

目标：为锻炼系统设计思维，系统掌握 system design。语言：Python。

## 规则

- 每天两道题：一道 **动手实现题**（写能跑的 Python 代码，通过测试），一道 **系统设计题**（按面试流程写设计文档）。
- 题目由 Claude 出，代码和设计全部自己写。
- 每天一个分支 / 一个讨论线程，做完提交后请 Claude review。

学习路线见 [ROADMAP.md](ROADMAP.md)。

## 目录结构

```
days/
  day-01/
    1-<动手题>/
      README.md        # 题目（Claude 写）
      solution.py      # 你的实现（只有函数签名的骨架）
      test_solution.py # 验收测试（Claude 写，你可以加更多）
    2-<设计题>/
      README.md        # 题目、规模、约束（Claude 写）
      DESIGN.md        # 你的设计文档（按模板填写）
templates/
  coding/README.md     # 动手题模板
  design/DESIGN.md     # 设计文档模板（面试答题框架）
```

## 运行测试

```bash
pip install -r requirements-dev.txt
pytest days/day-01
```

## 每天的流程

1. Claude 在当天的线程里出两道题，并把题目放进 `days/day-XX/`。
2. 动手题：先读题和测试，写 `solution.py`，跑通 `pytest`。
3. 设计题：限时 45 分钟，按 `DESIGN.md` 模板写，像真实面试一样先澄清需求再画架构。
4. 提交后告诉 Claude，Claude 会 review 代码和设计，并追问 2 到 3 个面试官常问的延伸问题。
