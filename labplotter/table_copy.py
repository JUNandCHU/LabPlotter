"""Read-only text selection inside a ttk Treeview cell."""
import tkinter as tk
from tkinter import ttk, font as tkfont


class SelectableTreeCells:
    def __init__(self, tree, columns=None):
        self.tree = tree
        self.columns = set(columns or tree['columns'])
        self.entry = None
        self.anchor = None
        self.bounds = None
        self.last_value = ''
        tree.bind('<ButtonPress-1>', self.press, add=True)
        tree.bind('<B1-Motion>', self.drag, add=True)
        tree.bind('<ButtonRelease-1>', self.release, add=True)
        tree.bind('<Control-c>', lambda _: self.copy_value(), add=True)
        tree.bind('<Control-C>', lambda _: self.copy_value(), add=True)
        for event in ('<Configure>', '<MouseWheel>', '<Button-4>', '<Button-5>'):
            tree.bind(event, lambda _: self.hide(), add=True)
        # Hide the temporary cell on either scrollbar's changes, including
        # keyboard scrolling. Retain the original scrollbar callbacks.
        for option in ('xscrollcommand', 'yscrollcommand'):
            original = tree.cget(option)
            def changed(*args, callback=original):
                self.hide()
                if callback: tree.tk.call(callback, *args)
            tree.configure(**{option: changed})

    def hide(self):
        if self.entry is not None:
            self.entry.destroy()
            self.entry = None
        self.anchor = self.bounds = None

    def press(self, event):
        self.hide()
        tree = self.tree
        if tree.identify_region(event.x, event.y) != 'cell': return
        iid, column = tree.identify_row(event.y), tree.identify_column(event.x)
        if not iid or not column: return
        index = int(column[1:])-1
        if tree['columns'][index] not in self.columns: return
        bounds = tree.bbox(iid, column)
        if not bounds: return
        tree.selection_set(iid); tree.focus(iid)
        self.last_value = str(tree.item(iid, 'values')[index])
        self.entry = ttk.Entry(tree, font=tkfont.nametofont('TkDefaultFont'), exportselection=False)
        self.entry.insert(0, self.last_value)
        self.entry.configure(state='readonly')
        self.bounds = bounds
        x, y, width, height = bounds
        self.entry.place(x=x, y=y, width=width, height=height)
        self.entry.lift(); self.entry.focus_set()
        self.anchor = self.entry.index(f'@{max(0,event.x-x)}')
        self.entry.icursor(self.anchor)
        self.entry.bind('<Escape>', lambda _: self.hide())
        return 'break'

    def drag(self, event):
        if self.entry is None or self.anchor is None: return
        index = self.entry.index(f'@{max(0,event.x-self.bounds[0])}')
        self.entry.selection_range(min(self.anchor, index), max(self.anchor, index))
        self.entry.icursor(index)
        return 'break'

    def release(self, event):
        if self.entry is not None and self.anchor is not None:
            self.drag(event)
            self.anchor = None
            return 'break'

    def _copy(self, value):
        self.tree.clipboard_clear(); self.tree.clipboard_append(value)
        return 'break'

    def copy_value(self):
        if self.entry is not None:
            # This button copies the complete cell. Native Entry Ctrl+C still
            # copies only the text that the user selected by dragging.
            return self._copy(self.entry.get())
        selected = self.tree.selection()
        if selected:
            columns = list(self.tree['columns'])
            index = columns.index('value') if 'value' in columns else len(columns)-1
            return self._copy(str(self.tree.item(selected[0], 'values')[index]))
        return 'break'

    def copy_table(self):
        columns = self.tree['columns']
        rows = [[self.tree.heading(key, 'text') for key in columns]]
        rows += [self.tree.item(iid, 'values') for iid in self.tree.get_children()]
        return self._copy('\n'.join('\t'.join(str(v) for v in row) for row in rows))
