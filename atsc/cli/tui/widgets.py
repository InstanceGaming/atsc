from asciimatics.widgets import Widget


class RenderedTextWidget(Widget):

    def update(self, frame_no):
        pass

    def reset(self):
        pass

    def process_event(self, event):
        Widget.process_event(self, event)

    def required_height(self, offset, width):
        return 1
