"""Install basic translation and OCR resources from the command line."""
from threading import Event
from .resources import byte_label, install_resources


def print_progress(event):
    detail = f"{byte_label(event['done'])}/{byte_label(event['total'])}" if event['phase'] == 'download' else event['phase']
    print(f"[{event['index']}/{event['count']}] {event['resource']}: {detail}", flush=True)


def main():
    install_resources(('basic',), Event(), print_progress)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
