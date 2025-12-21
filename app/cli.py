from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from adapters.excalidraw.repository import FileSystemExcalidrawRepository
from adapters.filesystem.markup_repository import FileSystemMarkupRepository
from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter

app = typer.Typer(no_args_is_help=True)
convert_app = typer.Typer(no_args_is_help=True)
app.add_typer(convert_app, name="convert")
console = Console()


@convert_app.command("to-excalidraw")
def convert_to_excalidraw(
    input_dir: Path = typer.Option(
        Path("data/markup"), help="Directory with markup JSON files.",
    ),
    output_dir: Path = typer.Option(
        Path("data/excalidraw_in"), help="Directory to write Excalidraw scene files.",
    ),
) -> None:
    markup_repo = FileSystemMarkupRepository()
    excal_repo = FileSystemExcalidrawRepository()
    layout = GridLayoutEngine()
    converter = MarkupToExcalidrawConverter(layout)

    pairs = markup_repo.load_all_with_paths(input_dir)
    if not pairs:
        console.print(f"[yellow]No markup files found in {input_dir}[/]")
        raise typer.Exit(code=0)

    output_dir.mkdir(parents=True, exist_ok=True)
    for path, document in pairs:
        excal_doc = converter.convert(document)
        target_path = output_dir / f"{path.stem}.excalidraw"
        excal_repo.save(excal_doc, target_path)
        console.print(f"[green]Wrote[/] {target_path}")


@convert_app.command("from-excalidraw")
def convert_from_excalidraw(
    input_dir: Path = typer.Option(
        Path("data/excalidraw_out"), help="Directory with .excalidraw/.json files from UI export.",
    ),
    output_dir: Path = typer.Option(
        Path("data/roundtrip"), help="Directory to write reconstructed markup JSON files.",
    ),
) -> None:
    excal_repo = FileSystemExcalidrawRepository()
    markup_repo = FileSystemMarkupRepository()
    converter = ExcalidrawToMarkupConverter()

    pairs = excal_repo.load_all_with_paths(input_dir)
    if not pairs:
        console.print(f"[yellow]No Excalidraw files found in {input_dir}[/]")
        raise typer.Exit(code=0)

    output_dir.mkdir(parents=True, exist_ok=True)
    for path, document in pairs:
        markup = converter.convert(document.to_dict())
        target_path = output_dir / f"{path.stem}.json"
        markup_repo.save(markup, target_path)
        console.print(f"[green]Wrote[/] {target_path}")


@app.command("validate")
def validate(input_path: Path = typer.Argument(..., help="Markup or Excalidraw file to validate.")) -> None:
    if not input_path.exists():
        console.print(f"[red]File not found:[/] {input_path}")
        raise typer.Exit(code=1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    try:
        if "elements" in data:
            converter = ExcalidrawToMarkupConverter()
            converter.convert(data)
            console.print(f"[green]Valid Excalidraw scene for conversion:[/] {input_path}")
        else:
            MarkupDocument.model_validate(data)
            console.print(f"[green]Valid markup file:[/] {input_path}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Validation failed:[/] {exc}")
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":
    app()
