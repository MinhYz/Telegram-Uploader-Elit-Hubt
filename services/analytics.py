from pathlib import Path
from typing import List, Dict, Tuple
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from config.settings import SCREENSHOT_DIR
from utils.logger import logger

class GradeAnalyticsService:
    """Grade & Feedback Tracker, Performance Chart Plotter, Final Exam Predictor."""

    @staticmethod
    def calculate_required_final_exam_score(
        current_grades: List[float], weights: List[float], target_final_grade: float = 8.0
    ) -> float:
        """
        Predict required final exam score for target overall course grade.
        Formula: Target = Sum(Grade_i * Weight_i) + Final_Score * Final_Weight
        """
        if not current_grades or not weights:
            return 8.0

        accumulated = sum(g * w for g, w in zip(current_grades, weights[:-1]))
        final_weight = weights[-1]

        if final_weight <= 0:
            return 0.0

        required_score = (target_final_grade - accumulated) / final_weight
        return max(0.0, min(10.0, round(required_score, 2)))

    @staticmethod
    def generate_performance_chart(course_name: str, grades_data: List[Dict[str, float]]) -> Path:
        """Plot student grade trend chart using matplotlib."""
        chart_path = SCREENSHOT_DIR / f"grade_chart_{int(matplotlib.dates.date2num(matplotlib.dates.datetime.datetime.now()))}.png"

        try:
            titles = [d.get("title", f"Bài {i+1}") for i, d in enumerate(grades_data)]
            scores = [d.get("score", 0.0) for d in grades_data]

            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.plot(titles, scores, marker="o", color="#003366", linewidth=2.5, markersize=8)
            ax.set_title(f"Biểu đồ Tiến độ Điểm số - {course_name}", fontsize=14, fontweight="bold", pad=15)
            ax.set_ylabel("Điểm số (Thang điểm 10)", fontsize=11)
            ax.set_ylim(0, 10)
            ax.grid(True, linestyle="--", alpha=0.6)

            for i, txt in enumerate(scores):
                ax.annotate(f"{txt}", (titles[i], scores[i]), textcoords="offset points", xytext=(0, 10), ha="center", fontweight="bold")

            plt.tight_layout()
            plt.savefig(chart_path, dpi=200)
            plt.close()
            logger.info(f"Generated grade performance chart at {chart_path}")
            return chart_path
        except Exception as e:
            logger.error(f"Error generating performance chart: {e}")
            plt.close()
            return chart_path

grade_analytics = GradeAnalyticsService()
