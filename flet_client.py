"""Compatibility launcher for the primary Flet client."""

from clients.flet_client_main import main


if __name__ == "__main__":
    import flet as ft

    ft.run(main, view=ft.AppView.FLET_APP)
