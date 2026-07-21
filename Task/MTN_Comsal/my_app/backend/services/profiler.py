"""数据质量分析引擎 - 向量化操作"""
import pandas as pd
import numpy as np
from typing import Dict, List, Any


class DataProfiler:
    """自动字段识别与数据质量分析"""

    @staticmethod
    def profile_table(df: pd.DataFrame) -> Dict[str, Any]:
        """对整个表进行字段画像分析"""
        result = {
            "total_rows": len(df),
            "total_cols": len(df.columns),
            "columns": [],
            "quality_score": 0,
            "issues_summary": [],
        }

        total_issues = 0
        total_checks = 0

        for col in df.columns:
            col_profile = DataProfiler._profile_column(df, col)
            result["columns"].append(col_profile)
            total_issues += col_profile.get("issue_count", 0)
            total_checks += 5  # 每列5项检查

        # 质量分数：100 - (问题数/检查总数 * 100)
        if total_checks > 0:
            result["quality_score"] = round(100 - (total_issues / total_checks * 100), 1)

        # 汇总问题
        for col_info in result["columns"]:
            if col_info.get("issues"):
                for issue in col_info["issues"]:
                    result["issues_summary"].append({
                        "column": col_info["name"],
                        "type": issue["type"],
                        "severity": issue["severity"],
                        "description": issue["description"],
                    })

        return result

    @staticmethod
    def _profile_column(df: pd.DataFrame, col: str) -> Dict[str, Any]:
        """单列画像分析"""
        series = df[col]
        profile = {
            "name": col,
            "dtype": str(series.dtype),
            "type_category": DataProfiler._infer_type(series),
            "total": len(series),
            "non_null": int(series.notna().sum()),
            "null_count": int(series.isna().sum()),
            "null_rate": round(series.isna().sum() / len(series) * 100, 2),
            "unique_count": int(series.nunique()),
            "unique_rate": round(series.nunique() / len(series) * 100, 2) if len(series) > 0 else 0,
            "duplicate_rate": round((1 - series.nunique() / len(series.dropna())) * 100, 2) if series.notna().sum() > 0 else 0,
            "issues": [],
            "issue_count": 0,
            "stats": {},
            "top_values": [],
        }

        # 数值型统计
        if pd.api.types.is_numeric_dtype(series):
            profile["stats"] = {
                "mean": round(float(series.mean()), 4) if series.notna().any() else None,
                "median": round(float(series.median()), 4) if series.notna().any() else None,
                "std": round(float(series.std()), 4) if series.notna().any() else None,
                "min": round(float(series.min()), 4) if series.notna().any() else None,
                "max": round(float(series.max()), 4) if series.notna().any() else None,
                "q25": round(float(series.quantile(0.25)), 4) if series.notna().any() else None,
                "q75": round(float(series.quantile(0.75)), 4) if series.notna().any() else None,
            }
            # 离群值检测（IQR方法）
            if series.notna().sum() > 10:
                q1 = series.quantile(0.25)
                q3 = series.quantile(0.75)
                iqr = q3 - q1
                outliers = ((series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)).sum()
                profile["outlier_count"] = int(outliers)
                profile["outlier_rate"] = round(outliers / series.notna().sum() * 100, 2)
                if outliers > 0:
                    profile["issues"].append({
                        "type": "outlier",
                        "severity": "warning" if outliers / series.notna().sum() < 0.05 else "error",
                        "description": f"检测到 {outliers} 个离群值 ({profile['outlier_rate']}%)",
                    })
                    profile["issue_count"] += 1

        # 文本型统计
        elif pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            str_series = series.dropna().astype(str)
            if len(str_series) > 0:
                profile["stats"] = {
                    "avg_length": round(float(str_series.str.len().mean()), 2),
                    "max_length": int(str_series.str.len().max()),
                    "min_length": int(str_series.str.len().min()),
                }

        # Top值
        if series.notna().sum() > 0:
            top = series.value_counts().head(10)
            profile["top_values"] = [
                {"value": str(k), "count": int(v), "rate": round(v / len(series) * 100, 2)}
                for k, v in top.items()
            ]

        # 质量问题检测
        # 1. 高空值率
        if profile["null_rate"] > 50:
            profile["issues"].append({
                "type": "high_null_rate",
                "severity": "error",
                "description": f"空值率过高 ({profile['null_rate']}%)",
            })
            profile["issue_count"] += 1
        elif profile["null_rate"] > 20:
            profile["issues"].append({
                "type": "moderate_null_rate",
                "severity": "warning",
                "description": f"空值率偏高 ({profile['null_rate']}%)",
            })
            profile["issue_count"] += 1

        # 2. 全重复
        if profile["unique_count"] == 1 and profile["non_null"] > 0:
            profile["issues"].append({
                "type": "constant_column",
                "severity": "warning",
                "description": "该列只有单一值，可能无分析价值",
            })
            profile["issue_count"] += 1

        # 3. 高度倾斜分布
        if len(profile["top_values"]) > 0 and profile["top_values"][0]["rate"] > 90:
            profile["issues"].append({
                "type": "skewed_distribution",
                "severity": "info",
                "description": f"Top1值 '{profile['top_values'][0]['value']}' 占比 {profile['top_values'][0]['rate']}%",
            })
            profile["issue_count"] += 1

        # 4. 潜在主键检测
        if profile["unique_count"] == len(series.dropna()) and profile["null_count"] == 0:
            profile["is_candidate_key"] = True

        return profile

    @staticmethod
    def _infer_type(series: pd.Series) -> str:
        """推断字段业务类型"""
        col_lower = series.name.lower() if isinstance(series.name, str) else ""

        # 按列名推断
        if any(k in col_lower for k in ['lat', 'latitude']):
            return "地理-纬度"
        if any(k in col_lower for k in ['lon', 'lng', 'longitude']):
            return "地理-经度"
        if any(k in col_lower for k in ['time', 'date', 'created', 'modified', 'updated']):
            return "时间"
        if any(k in col_lower for k in ['id', 'no', 'number', 'code']):
            return "标识符"
        if any(k in col_lower for k in ['name', 'title', 'description']):
            return "文本描述"
        if any(k in col_lower for k in ['status', 'type', 'category', 'class', 'level']):
            return "分类"
        if any(k in col_lower for k in ['region', 'province', 'county', 'area']):
            return "地理区域"
        if any(k in col_lower for k in ['count', 'amount', 'quantity', 'total']):
            return "计数/数量"
        if any(k in col_lower for k in ['sla', 'duration', 'time']):
            return "时长/SLA"

        # 按数据类型推断
        if pd.api.types.is_numeric_dtype(series):
            if series.nunique() <= 10:
                return "数值-离散(少量)"
            return "数值-连续"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "日期时间"
        if pd.api.types.is_bool_dtype(series):
            return "布尔"

        # 文本型进一步判断
        if pd.api.types.is_object_dtype(series):
            non_null = series.dropna()
            if len(non_null) > 0:
                sample = non_null.iloc[0]
                if isinstance(sample, str):
                    if len(non_null.unique()) / len(non_null) < 0.1:
                        return "文本-分类"
                    return "文本-自由文本"
            return "文本"

        return "未知"

    @staticmethod
    def generate_conclusions(profile: Dict) -> List[str]:
        """基于画像生成分析结论"""
        conclusions = []
        cols = profile.get("columns", [])

        # 数据规模
        conclusions.append(f"数据集包含 {profile['total_rows']:,} 行 × {profile['total_cols']} 列")

        # 质量分数
        score = profile["quality_score"]
        if score >= 90:
            conclusions.append(f"数据质量评分: {score}分 (优秀)")
        elif score >= 70:
            conclusions.append(f"数据质量评分: {score}分 (良好)")
        else:
            conclusions.append(f"数据质量评分: {score}分 (需关注)")

        # 高空值列
        high_null_cols = [c for c in cols if c.get("null_rate", 0) > 50]
        if high_null_cols:
            conclusions.append(f"有 {len(high_null_cols)} 列空值率超过50%，建议评估是否保留")

        # 候选主键
        key_cols = [c["name"] for c in cols if c.get("is_candidate_key")]
        if key_cols:
            conclusions.append(f"候选主键列: {', '.join(key_cols[:5])}")

        # 分类字段（适合做维度分析）
        cat_cols = [c["name"] for c in cols if c.get("type_category") in ("分类", "文本-分类", "地理区域")]
        if cat_cols:
            conclusions.append(f"推荐分析维度: {', '.join(cat_cols[:8])}")

        # 数值字段（适合做度量分析）
        num_cols = [c["name"] for c in cols if "数值" in c.get("type_category", "") or c.get("type_category") in ("计数/数量", "时长/SLA")]
        if num_cols:
            conclusions.append(f"推荐分析度量: {', '.join(num_cols[:8])}")

        # 时间字段
        time_cols = [c["name"] for c in cols if c.get("type_category") == "时间" or c.get("type_category") == "日期时间"]
        if time_cols:
            conclusions.append(f"时间字段: {', '.join(time_cols[:5])}，可用于趋势分析")

        # 地理字段
        geo_cols = [c["name"] for c in cols if "地理" in c.get("type_category", "")]
        if geo_cols:
            conclusions.append(f"地理字段: {', '.join(geo_cols[:5])}，可用于GIS可视化")

        # 总问题数
        issue_count = len(profile.get("issues_summary", []))
        if issue_count > 0:
            error_count = sum(1 for i in profile["issues_summary"] if i["severity"] == "error")
            warning_count = sum(1 for i in profile["issues_summary"] if i["severity"] == "warning")
            conclusions.append(f"检测到 {issue_count} 个质量问题 (严重:{error_count}, 警告:{warning_count})")

        return conclusions
