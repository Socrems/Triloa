"""Install base subtitles, VAD and their translation resources explicitly."""
from threading import Event
from .install_models import print_progress
from .resources import install_resources


def main():
    install_resources(('subtitles',), Event(), print_progress)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
