"""Excel 파일 읽기 및 LLM 친화적 JSON 변환 도구."""

import json
import logging
import sys
from pathlib import Path
from typing import Any

import openpyxl
import pandas as pd

_LOG_FILE = Path(__file__).parent / "reader.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def get_excel_sheets(file_path: str) -> list[str]:
    """엑셀 파일의 모든 시트명을 반환합니다."""
    try:
        wb = openpyxl.load_workbook(file_path, data_only=False)
        sheets = wb.sheetnames
        wb.close()
        logger.info("엑셀 파일에서 %d개 시트 발견: %s", len(sheets), sheets)
        return sheets
    except Exception as e:
        logger.error("시트 목록 읽기 실패 (%s): %s", file_path, e)
        raise


def infer_column_type(series: pd.Series) -> str:
    """pandas Series에서 데이터 타입을 추론합니다."""
    if series.empty or series.isna().all():
        return "unknown"

    non_null = series.dropna()
    if non_null.empty:
        return "unknown"

    dtype = series.dtype

    if dtype == "object":
        first_val = non_null.iloc[0]
        if isinstance(first_val, bool):
            return "boolean"
        if isinstance(first_val, (int, float)):
            return "numeric"
        if isinstance(first_val, str):
            if all(
                str(v).lower() in ("true", "false", "yes", "no", "0", "1")
                for v in non_null[:10]
            ):
                return "boolean"
            return "string"
        return "string"

    if dtype in ("int64", "int32", "int16", "int8"):
        return "integer"
    if dtype in ("float64", "float32"):
        return "float"
    if dtype == "bool":
        return "boolean"
    if "datetime" in str(dtype):
        return "datetime"

    return str(dtype)


def extract_sheet_metadata(file_path: str, sheet_name: str) -> dict[str, Any]:
    """시트의 메타데이터와 컬럼 정보를 추출합니다."""
    try:
        df_str = pd.read_excel(file_path, sheet_name=sheet_name, dtype=str)
        df_typed = pd.read_excel(file_path, sheet_name=sheet_name)

        columns_info = []
        for col_idx, col_name in enumerate(df_str.columns, 1):
            col_data = df_typed[col_name]
            col_type = infer_column_type(col_data)

            non_null_count = col_data.notna().sum()
            null_count = col_data.isna().sum()

            sample_values = (
                col_data.dropna().unique()[:5].tolist()
                if not col_data.empty
                else []
            )

            columns_info.append({
                "index": col_idx,
                "name": str(col_name),
                "type": col_type,
                "non_null_count": int(non_null_count),
                "null_count": int(null_count),
                "sample_values": sample_values,
            })

        metadata = {
            "sheet_name": sheet_name,
            "row_count": len(df_str),
            "column_count": len(df_str.columns),
            "columns": columns_info,
        }

        logger.info(
            "시트 '%s' 메타데이터 추출 완료 (행: %d, 열: %d)",
            sheet_name, len(df_str), len(df_str.columns),
        )
        return metadata

    except Exception as e:
        logger.error("시트 메타데이터 추출 실패 ('%s'): %s", sheet_name, e)
        raise


def read_excel_to_json(file_path: str) -> dict[str, Any]:
    """엑셀 파일 전체를 분석하여 LLM 친화적 JSON으로 변환합니다."""
    file_path = str(file_path)

    if not Path(file_path).exists():
        logger.error("파일을 찾을 수 없음: %s", file_path)
        raise FileNotFoundError(f"파일을 찾을 수 없음: {file_path}")

    if not file_path.lower().endswith(".xlsx"):
        logger.error("지원하지 않는 형식: %s (지원 형식: .xlsx)", file_path)
        raise ValueError("xlsx 형식의 파일만 지원합니다. (.xls 등 다른 형식은 미지원)")

    logger.info("엑셀 파일 읽기 시작: %s", file_path)

    try:
        sheets = get_excel_sheets(file_path)
        sheets_data = []

        for sheet_name in sheets:
            try:
                metadata = extract_sheet_metadata(file_path, sheet_name)
                sheets_data.append(metadata)
            except Exception as e:
                logger.warning("시트 '%s' 처리 중 오류 발생: %s", sheet_name, e)
                sheets_data.append({
                    "sheet_name": sheet_name,
                    "error": str(e),
                })

        result = {
            "file_path": file_path,
            "total_sheets": len(sheets),
            "sheets": sheets_data,
        }

        logger.info("엑셀 분석 완료: %d개 시트 처리됨", len(sheets))
        return result

    except Exception as e:
        logger.error("엑셀 파일 처리 실패: %s", e)
        raise


def save_schema_json(data: dict[str, Any], output_path: str = "schema.json") -> None:
    """분석 결과를 JSON 파일로 저장합니다."""
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("스키마 저장 완료: %s", output_path)
    except Exception as e:
        logger.error("JSON 저장 실패 (%s): %s", output_path, e)
        raise


def main() -> int:
    """CLI 진입점."""
    if len(sys.argv) < 2:
        sys.stdout.write("사용법: python excel_reader.py <엑셀파일경로> [출력파일경로]\n")
        sys.stdout.write("예: python excel_reader.py data.xlsx\n")
        sys.stdout.write("   python excel_reader.py data.xlsx output.json\n")
        return 1

    file_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "schema.json"

    try:
        result = read_excel_to_json(file_path)
        save_schema_json(result, output_path)
        sys.stdout.write(f"분석 완료: {output_path}\n")
        return 0
    except Exception as e:
        sys.stderr.write(f"오류 발생: {e}\n")
        logger.exception("프로그램 실행 중 예외 발생")
        return 1


if __name__ == "__main__":
    sys.exit(main())
