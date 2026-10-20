from __future__ import annotations

import shutil
import subprocess

import pytest
from openpyxl import load_workbook

from app.services.excel_export import build_project_workbook, export_project_workbook


@pytest.fixture
def workbook_data():
    project = {"id": 9, "nom": "Montage", "takt_s": 60.0}
    stations = [
        {
            "id": 1,
            "nom": "Poste A",
            "cycles": [
                {"debut_s": 0, "fin_s": 8, "source": "manual"},
                {"debut_s": 11, "fin_s": 21, "source": "auto"},
            ],
            "phases": [
                {
                    "ordre": 1,
                    "debut_s": 0.0,
                    "fin_s": 10.0,
                    "type_auto": "activity",
                    "description": "Monter le composant",
                    "categorie": "VA",
                    "commentaire": "Validé atelier",
                    "chrono_reel_s": 8.0,
                    "mouvement_moyen_pct": 42.0,
                },
                {
                    "ordre": 2,
                    "debut_s": 10.0,
                    "fin_s": 15.0,
                    "type_auto": "stop",
                    "description": "Attente",
                    "categorie": "Gaspillage",
                    "commentaire": "",
                    "chrono_reel_s": None,
                    "mouvement_moyen_pct": 1.0,
                },
            ],
        },
        {
            "id": 2,
            "nom": "Poste B",
            "phases": [
                {
                    "ordre": 1,
                    "debut_s": 0.0,
                    "fin_s": 12.0,
                    "type_auto": "activity",
                    "description": "Contrôler le produit",
                    "categorie": "NVA nécessaire",
                    "commentaire": "",
                    "chrono_reel_s": 12.0,
                    "mouvement_moyen_pct": 25.0,
                }
            ],
        },
    ]
    return project, stations


def test_excel_export_has_formulas_margin_validation_and_native_yamazumi(tmp_path, workbook_data):
    project, stations = workbook_data
    path = build_project_workbook(project, stations, tmp_path / "study.xlsx")

    formulas = load_workbook(path, data_only=False)
    assert formulas.sheetnames == ["Synthèse", "Étapes", "Notes"]
    steps = formulas["Étapes"]
    summary = formulas["Synthèse"]

    assert steps["E2"].value == "=D2-C2"
    assert steps["K2"].value == '=IF(OR(J2="",J2=0),"",ABS((E2-J2)/J2))'
    assert steps["E5"].value == "=D5-C5"
    assert steps["K5"].value == '=IF(OR(J5="",J5=0),"",ABS((E5-J5)/J5))'
    assert "G2:G64" in [str(validation.sqref) for validation in steps.data_validations.dataValidation]
    assert summary["B6"].value.startswith("=SUMIFS('Étapes'!")
    assert summary["F6"].value == "=SUM(B6:E6)"
    assert summary["H6"].value == "=IF(F6=0,0,B6/F6)"
    assert summary["I6"].value == "=IF(G6=0,0,F6-G6)"
    assert summary["J6"].value.startswith("=IFERROR(AVERAGEIF(")
    assert len(summary._charts) == 1
    assert summary._charts[0].type == "col"
    assert len(summary._charts[0]._charts) == 2
    assert [type(chart).__name__ for chart in summary._charts[0]._charts] == ["BarChart", "LineChart"]
    assert steps["A2"].font.color.rgb.endswith("0000FF")
    assert steps["E2"].font.color.rgb.endswith("000000")
    assert all(cell.font.name == "Arial" for sheet in formulas for row in sheet.iter_rows() for cell in row if cell.value is not None)
    notes = formulas["Notes"]
    assert notes["A11"].value == "Poste"
    assert notes["E12"].value == "=D12-C12"
    assert notes["F13"].value == "Proposition automatique vérifiée"


def test_export_retries_with_timestamped_filename_after_write_error(tmp_path, workbook_data, monkeypatch):
    import app.services.excel_export as excel_export

    project, stations = workbook_data
    original = excel_export.build_project_workbook
    calls = 0

    def fail_first_write(project_arg, stations_arg, output_path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("fichier verrouillé")
        return original(project_arg, stations_arg, output_path)

    monkeypatch.setattr(excel_export, "build_project_workbook", fail_first_write)
    target = tmp_path / "locked.xlsx"
    path, warning = export_project_workbook(project, stations, target)

    assert path.exists()
    assert path != target
    assert "fichier verrouillé" in warning
    assert path.stem.startswith("locked_")


def test_exported_formulas_recalculate_without_spreadsheet_errors(tmp_path, workbook_data):
    libreoffice = shutil.which("soffice") or shutil.which("libreoffice")
    if libreoffice is None:
        pytest.skip("LibreOffice n'est pas installé ; vérification structurelle des formules effectuée séparément.")

    project, stations = workbook_data
    source = build_project_workbook(project, stations, tmp_path / "study.xlsx")
    output_dir = tmp_path / "recalculated"
    output_dir.mkdir()
    subprocess.run(
        [
            libreoffice,
            "--headless",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(output_dir),
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    recalculated_path = output_dir / source.name
    assert recalculated_path.exists()
    workbook = load_workbook(recalculated_path, data_only=True)
    assert workbook["Étapes"]["E2"].value == 10
    assert workbook["Synthèse"]["B6"].value == 10
    assert workbook["Synthèse"]["D6"].value == 5
    assert workbook["Synthèse"]["F6"].value == 15
    assert workbook["Synthèse"]["H6"].value == pytest.approx(10 / 15)
    assert workbook["Synthèse"]["J6"].value == pytest.approx(25.0)
    assert not any(
        isinstance(cell.value, str) and cell.value.startswith("#")
        for sheet in workbook
        for row in sheet.iter_rows()
        for cell in row
    )
