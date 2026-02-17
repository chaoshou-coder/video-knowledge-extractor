"""
Workflow Monitor - 监控 OpenCode 工作流执行
自动检测失败和越权行为
"""

import re
from dataclasses import dataclass
from typing import List
from datetime import datetime


@dataclass
class WorkflowEvent:
    """工作流事件"""

    timestamp: str
    level: str  # INFO, WARNING, ERROR, CRITICAL
    agent: str
    action: str
    details: str
    should_stop: bool = False


@dataclass
class WorkflowReport:
    """工作流执行报告"""

    total_events: int
    errors: int
    warnings: int
    critical_issues: List[str]
    recommendations: List[str]
    should_halt: bool


class WorkflowMonitor:
    """工作流监控器"""

    # 越权行为模式
    UNAUTHORIZED_PATTERNS = [
        r"(删除|修改|重写).*用户.*文件",
        r"(修改|变更).*git.*配置",
        r"(访问|读取).*密码|密钥|token",
        r"(执行|运行).*系统.*命令",
        r"(安装|卸载).*系统.*包",
    ]

    # 失败模式
    FAILURE_PATTERNS = [
        r"error|exception|failed|timeout",
        r"无法.*连接|connection.*refused",
        r"权限.*拒绝|permission.*denied",
        r"资源.*不足|resource.*exhausted",
    ]

    def __init__(self, log_file: str = "workflow.log"):
        self.log_file = log_file
        self.events: List[WorkflowEvent] = []
        self.critical_count = 0
        self.error_count = 0
        self.warning_count = 0

    def analyze_log(self, log_content: str) -> WorkflowReport:
        """分析工作流日志"""
        lines = log_content.split("\n")

        for line in lines:
            self._analyze_line(line)

        return self._generate_report()

    def _analyze_line(self, line: str):
        """分析单行日志"""
        # 检测越权行为
        for pattern in self.UNAUTHORIZED_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                self.events.append(
                    WorkflowEvent(
                        timestamp=datetime.now().isoformat(),
                        level="CRITICAL",
                        agent="unknown",
                        action="unauthorized_access",
                        details=f"检测到越权行为: {line[:100]}",
                        should_stop=True,
                    )
                )
                self.critical_count += 1
                return

        # 检测失败
        for pattern in self.FAILURE_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                self.events.append(
                    WorkflowEvent(
                        timestamp=datetime.now().isoformat(),
                        level="ERROR",
                        agent="unknown",
                        action="execution_failure",
                        details=f"执行失败: {line[:100]}",
                        should_stop=False,
                    )
                )
                self.error_count += 1
                return

        # 检测警告
        if "warning" in line.lower() or "warn" in line.lower():
            self.events.append(
                WorkflowEvent(
                    timestamp=datetime.now().isoformat(),
                    level="WARNING",
                    agent="unknown",
                    action="potential_issue",
                    details=line[:100],
                )
            )
            self.warning_count += 1

    def _generate_report(self) -> WorkflowReport:
        """生成监控报告"""
        critical_issues = [e.details for e in self.events if e.level == "CRITICAL"]

        recommendations = []

        if self.critical_count > 0:
            recommendations.append("立即停工：检测到越权行为，需人工审查")

        if self.error_count > 3:
            recommendations.append("建议停工：错误过多，工作流可能不稳定")

        if self.warning_count > 10:
            recommendations.append("关注：警告数量较多，建议检查")

        should_halt = self.critical_count > 0 or self.error_count > 5

        return WorkflowReport(
            total_events=len(self.events),
            errors=self.error_count,
            warnings=self.warning_count,
            critical_issues=critical_issues,
            recommendations=recommendations,
            should_halt=should_halt,
        )

    def monitor_live(self, process_output: str) -> bool:
        """
        实时监控进程输出

        Returns:
            bool: 是否继续执行（False = 停工）
        """
        self._analyze_line(process_output)

        # 检查最后的事件
        if self.events and self.events[-1].should_stop:
            return False

        # 检查错误阈值
        if self.error_count > 5:
            return False

        return True


# 使用示例
if __name__ == "__main__":
    monitor = WorkflowMonitor()

    # 模拟日志分析
    sample_log = """
    [INFO] Starting OpenCode agent
    [INFO] Reading file: src/workflow.py
    [WARNING] Type mismatch detected
    [ERROR] Failed to connect to API
    [INFO] Retrying...
    [ERROR] Retry failed
    """

    report = monitor.analyze_log(sample_log)
    print(f"Total events: {report.total_events}")
    print(f"Should halt: {report.should_halt}")
    for rec in report.recommendations:
        print(f"Recommendation: {rec}")
