from __future__ import annotations

import json
from pathlib import Path

import typer
import uvicorn
from adapters.excalidraw.repository import FileSystemExcalidrawRepository
from adapters.filesystem.catalog_index_repository import FileSystemCatalogIndexRepository
from adapters.filesystem.markup_repository import FileSystemMarkupRepository
from adapters.layout.grid import GridLayoutEngine
from domain.models import MarkupDocument
from domain.ports.repositories import MarkupRepository
from domain.services.build_catalog_index import BuildCatalogIndex
from domain.services.convert_excalidraw_to_markup import ExcalidrawToMarkupConverter
from domain.services.convert_markup_to_excalidraw import MarkupToExcalidrawConverter
from rich.console import Console

from app.catalog_wiring import build_markup_repository, build_markup_source
from app.config import AppSettings, load_settings

app = typer.Typer(no_args_is_help=True)
convert_app = typer.Typer(no_args_is_help=True)
catalog_app = typer.Typer(no_args_is_help=True)
pipeline_app = typer.Typer(no_args_is_help=True)
app.add_typer(convert_app, name="convert")
app.add_typer(catalog_app, name="catalog")
app.add_typer(pipeline_app, name="pipeline")
console = Console()


def _run_convert_to_excalidraw(
    input_dir: Path,
    output_dir: Path,
    markup_repo: MarkupRepository | None = None,
) -> None:
    markup_repo = markup_repo or FileSystemMarkupRepository()
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


def _run_convert_from_excalidraw(input_dir: Path, output_dir: Path) -> None:
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


def _run_build_index_from_settings(settings: AppSettings) -> None:
    builder = BuildCatalogIndex(
        build_markup_source(settings),
        FileSystemCatalogIndexRepository(),
    )
    index = builder.build(settings.catalog.to_index_config())
    console.print(f"[green]Catalog index ready:[/] {settings.catalog.index_path}")
    console.print(f"[green]Scenes indexed:[/] {len(index.items)}")


def _run_build_index(config_path: Path) -> None:
    settings = load_settings(config_path)
    _run_build_index_from_settings(settings)


@convert_app.command("to-excalidraw")
def convert_to_excalidraw(
    input_dir: Path = typer.Option(
        Path("data/markup"),
        help="Directory with markup JSON files.",
    ),
    output_dir: Path = typer.Option(
        Path("data/excalidraw_in"),
        help="Directory to write Excalidraw scene files.",
    ),
) -> None:
    _run_convert_to_excalidraw(input_dir, output_dir)


@convert_app.command("from-excalidraw")
def convert_from_excalidraw(
    input_dir: Path = typer.Option(
        Path("data/excalidraw_out"),
        help="Directory with .excalidraw/.json files from UI export.",
    ),
    output_dir: Path = typer.Option(
        Path("data/roundtrip"),
        help="Directory to write reconstructed markup JSON files.",
    ),
) -> None:
    _run_convert_from_excalidraw(input_dir, output_dir)


@app.command("validate")
def validate(
    input_path: Path = typer.Argument(..., help="Markup or Excalidraw file to validate."),
) -> None:
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
    except Exception as exc:
        console.print(f"[red]Validation failed:[/] {exc}")
        raise typer.Exit(code=1) from exc


@catalog_app.command("build-index")
def catalog_build_index(
    config: Path = typer.Option(
        Path("config/catalog/app.s3.yaml"),
        help="Path to catalog config YAML.",
    ),
) -> None:
    _run_build_index(config)


@catalog_app.command("serve")
def catalog_serve(
    host: str = typer.Option("0.0.0.0", help="Host to bind the Catalog UI."),
    port: int = typer.Option(8080, help="Port to bind the Catalog UI."),
    config: Path = typer.Option(
        Path("config/catalog/app.s3.yaml"),
        help="Path to catalog config YAML.",
    ),
) -> None:
    settings = load_settings(config)
    from app.web_main import create_app

    uvicorn.run(create_app(settings), host=host, port=port)


@pipeline_app.command("build-all")
def pipeline_build_all(
    config: Path = typer.Option(
        Path("config/catalog/app.s3.yaml"),
        help="Path to catalog config YAML.",
    ),
) -> None:
    settings = load_settings(config)
    markup_repo = build_markup_repository(settings)
    markup_dir = Path(settings.catalog.s3.prefix or "")
    _run_convert_to_excalidraw(markup_dir, settings.catalog.excalidraw_in_dir, markup_repo)
    _run_build_index_from_settings(settings)


if __name__ == "__main__":
    app()
