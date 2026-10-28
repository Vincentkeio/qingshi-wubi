# -*- coding: utf-8 -*-
"""极薄的 Win32 / GDI 绑定层：只封装设置中心用到的那部分。

设计原则：
- 不引任何第三方包（ctypes 直调 user32 / gdi32 / comctl32 / comdlg32）；
- 每个窗口对象挂在 hwnd 上，消息回调里按 hwnd 找到 Python 对象再分发；
- 尺寸单位统一用「96 DPI 下的像素」，由调用方乘缩放系数。
"""
import ctypes
import ctypes.wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
comctl32 = ctypes.WinDLL("comctl32", use_last_error=True)
comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
HINSTANCE = wt.HINSTANCE
HWND = wt.HWND
HDC = wt.HDC
HMENU = wt.HMENU
HBRUSH = wt.HBRUSH
HFONT = wt.HFONT
HPEN = wt.HPEN
HGDIOBJ = wt.HGDIOBJ

# ---- window styles ----
WS_OVERLAPPED = 0x00000000
WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_MINIMIZE = 0x20000000
WS_VISIBLE = 0x10000000
WS_DISABLED = 0x08000000
WS_CLIPSIBLINGS = 0x04000000
WS_CLIPCHILDREN = 0x02000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_VSCROLL = 0x00200000
WS_HSCROLL = 0x00100000
WS_BORDER = 0x00800000
WS_TABSTOP = 0x00010000
WS_GROUP = 0x00020000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_CONTROLPARENT = 0x00010000
WS_EX_COMPOSITED = 0x02000000
WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_CLIENTEDGE = 0x00000200
WS_OVERLAPPEDWINDOW = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX

# ---- messages ----
WM_CREATE = 0x0001
WM_DESTROY = 0x0002
WM_SIZE = 0x0005
WM_ACTIVATE = 0x0006
WM_SETFOCUS = 0x0007
WM_KILLFOCUS = 0x0008
WM_ENABLE = 0x000A
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_QUERYENDSESSION = 0x0011
WM_QUIT = 0x0012
WM_ERASEBKGND = 0x0014
WM_SHOWWINDOW = 0x0018
WM_SETTINGCHANGE = 0x001A
WM_SETCURSOR = 0x0020
WM_GETMINMAXINFO = 0x0024
WM_DRAWITEM = 0x002B
WM_MEASUREITEM = 0x002C
WM_COMMAND = 0x0111
WM_SYSCOMMAND = 0x0112
WM_TIMER = 0x0113
WM_HSCROLL = 0x0114
WM_VSCROLL = 0x0115
WM_INITMENUPOPUP = 0x0117
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEWHEEL = 0x020A
WM_MOUSELEAVE = 0x02A3
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_CTLCOLORSTATIC = 0x0138
WM_CTLCOLOREDIT = 0x0133
WM_CTLCOLORLISTBOX = 0x0134
WM_CTLCOLORBTN = 0x0135
WM_CTLCOLORDLG = 0x0136
WM_DPICHANGED = 0x02E0
WM_GETDLGCODE = 0x0087
WM_NOTIFY = 0x004E
WM_NCHITTEST = 0x0084
WM_NCPAINT = 0x0085
WM_NCACTIVATE = 0x0086
WM_APP = 0x8000

# ---- notifications / button styles ----
BN_CLICKED = 0
BN_SETFOCUS = 6
BN_KILLFOCUS = 7
BS_PUSHBUTTON = 0x00000000
BS_DEFPUSHBUTTON = 0x00000001
BS_CHECKBOX = 0x00000002
BS_AUTOCHECKBOX = 0x00000003
BS_RADIOBUTTON = 0x00000004
BS_3STATE = 0x00000005
BS_AUTO3STATE = 0x00000006
BS_GROUPBOX = 0x00000007
BS_AUTORADIOBUTTON = 0x00000009
BS_OWNERDRAW = 0x0000000B
BS_LEFT = 0x00000100
BS_FLAT = 0x00008000
BST_UNCHECKED = 0
BST_CHECKED = 1
BM_SETCHECK = 0x00F1
BM_GETCHECK = 0x00F0
BM_SETSTATE = 0x00F3
BM_CLICK = 0x00F5
BM_SETIMAGE = 0x00F7

# ---- static ----
SS_LEFT = 0x00000000
SS_CENTER = 0x00000001
SS_RIGHT = 0x00000002
SS_NOPREFIX = 0x00000080
SS_ENDELLIPSIS = 0x00004000

# ---- edit ----
ES_LEFT = 0x0000
ES_CENTER = 0x0001
ES_RIGHT = 0x0002
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
ES_AUTOHSCROLL = 0x0080
ES_READONLY = 0x0800
ES_NUMBER = 0x2000
EM_SETSEL = 0x00B1
EM_REPLACESEL = 0x00C2
EM_SETCUEBANNER = 0x1501
EM_GETLINE = 0x00C4
EM_LIMITTEXT = 0x00C5

# ---- combo ----
CBS_DROPDOWN = 0x0002
CBS_DROPDOWNLIST = 0x0003
CBS_OWNERDRAWFIXED = 0x0010
CBS_HASSTRINGS = 0x0200
CBS_NOINTEGRALHEIGHT = 0x0400
CB_ADDSTRING = 0x0143
CB_RESETCONTENT = 0x014B
CB_SETCURSEL = 0x014E
CB_GETCURSEL = 0x0147
CB_GETITEMDATA = 0x0150
CB_SETITEMDATA = 0x0151
CB_GETCOUNT = 0x0146
CB_SETDROPPEDWIDTH = 0x0160
CB_SHOWDROPDOWN = 0x014F
CBN_SELCHANGE = 1

# ---- listview ----
LVS_REPORT = 0x0001
LVS_SINGLESEL = 0x0004
LVS_SHOWSELALWAYS = 0x0008
LVS_NOSORTHEADER = 0x8000
LVS_EX_FULLROWSELECT = 0x00000020
LVS_EX_DOUBLEBUFFER = 0x00010000
LVS_EX_GRIDLINES = 0x00000001
LVS_EX_HEADERDRAGDROP = 0x00000010
LVM_FIRST = 0x1000
LVM_INSERTCOLUMNW = LVM_FIRST + 97
LVM_INSERTITEMW = LVM_FIRST + 77
LVM_SETITEMTEXTW = LVM_FIRST + 116
LVM_DELETEALLITEMS = LVM_FIRST + 9
LVM_GETNEXTITEM = LVM_FIRST + 12
LVM_SETCOLUMNWIDTH = LVM_FIRST + 30
LVM_SETEXTENDEDLISTVIEWSTYLE = LVM_FIRST + 54
LVM_SETITEMSTATE = LVM_FIRST + 43
LVM_GETSELECTEDCOUNT = LVM_FIRST + 50
LVM_ENSUREVISIBLE = LVM_FIRST + 19
LVNI_SELECTED = 0x0002
LVIS_SELECTED = 0x0002
LVIS_FOCUSED = 0x0001
LVCF_FMT = 0x0001
LVCF_WIDTH = 0x0002
LVCF_TEXT = 0x0004
LVCF_SUBITEM = 0x0008
LVIF_TEXT = 0x0001
LVIF_STATE = 0x0008
LVCFMT_LEFT = 0x0000
LVCFMT_CENTER = 0x0001
LVN_ITEMCHANGED = -101
LVN_DELETEALLITEMS = -105
NM_CLICK = -2
NM_DBLCLK = -3
NM_SETFOCUS = -7
NM_KILLFOCUS = -8

# ---- updown ----
UDS_ALIGNRIGHT = 0x0004
UDS_ARROWKEYS = 0x0020
UDS_SETBUDDYINT = 0x0002
UDS_WRAP = 0x0001
UDN_DELTAPOS = -721
UDM_SETRANGE32 = wt.UINT(0x046F)
UDM_SETPOS32 = wt.UINT(0x0471)
UDM_GETPOS32 = wt.UINT(0x0472)

# ---- misc ----
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOW = 5
SW_SHOWNA = 8
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
SWP_FRAMECHANGED = 0x0020
GWLP_USERDATA = -21
GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_HWNDNEXT = 2
GW_CHILD = 5
HWND_TOP = 0
CW_USEDEFAULT = -2147483648
HWND_TOPMOST = -1
DT_LEFT = 0x0000
DT_CENTER = 0x0001
DT_RIGHT = 0x0002
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
DT_END_ELLIPSIS = 0x00008000
DT_NOPREFIX = 0x00000800
DT_WORDBREAK = 0x0010
DT_CALCRECT = 0x0400
DT_TOP = 0x0000
DT_BOTTOM = 0x0008
DT_EDITCONTROL = 0x2000
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_GRAYED = 0x0001
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002
COLOR_WINDOW = 5
SRCCOPY = 0x00CC0020
IDC_ARROW = 32512
IDC_HAND = 32649
IDC_IBEAM = 32513
WM_SETREDRAW = 0x000B
RDW_INVALIDATE = 0x0001
RDW_ALLCHILDREN = 0x0080
RDW_ERASE = 0x0004
RDW_UPDATENOW = 0x0100
MB_OK = 0x00000000
MB_OKCANCEL = 0x00000001
MB_YESNO = 0x00000004
MB_ICONINFORMATION = 0x00000040
MB_ICONWARNING = 0x00000030
MB_ICONERROR = 0x00000010
MB_ICONQUESTION = 0x00000020
MB_TOPMOST = 0x00040000
MB_SETFOREGROUND = 0x00010000
IDOK = 1
IDCANCEL = 2
IDYES = 6
IDNO = 7
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_DEFAULTSIZE = 0x0040
LR_SHARED = 0x8000
OFN_OVERWRITEPROMPT = 0x00000002
OFN_FILEMUSTEXIST = 0x0001000
OFN_PATHMUSTEXIST = 0x00000800
OFN_NOCHANGEDIR = 0x00000008
OFN_EXPLORER = 0x00080000
SM_CXVSCROLL = 2
SM_CYSCROLL = 3
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SPI_GETWORKAREA = 0x0030
SB_LINEUP = 0
SB_LINEDOWN = 1
SB_PAGEUP = 2
SB_PAGEDOWN = 3
SB_THUMBPOSITION = 4
SB_THUMBTRACK = 5
SB_TOP = 6
SB_BOTTOM = 7
SB_ENDSCROLL = 8
SIF_ALL = 0x0017
SIF_POS = 0x0004
SIF_RANGE = 0x0001
SIF_PAGE = 0x0002
SIF_TRACKPOS = 0x0010
CS_DBLCLKS = 0x0008
CS_HREDRAW = 0x0002
CS_VREDRAW = 0x0001
CS_DROPSHADOW = 0x00020000
DEFAULT_CHARSET = 1
DEFAULT_GUI_FONT = 17
CLEARTYPE_QUALITY = 5
CLEARTYPE_NATURAL_QUALITY = 6
ANTIALIASED_QUALITY = 4
FW_NORMAL = 400
FW_MEDIUM = 500
FW_SEMIBOLD = 600
FW_BOLD = 700
PS_SOLID = 0
PS_NULL = 5
NULL_BRUSH = 5
HOLLOW_BRUSH = NULL_BRUSH
TRANSPARENT = 1
OPAQUE = 2
TA_LEFT = 0
TA_CENTER = 6
CLR_INVALID = 0xFFFFFFFF
# DPI
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("style", wt.UINT), ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE),
                ("hbrBackground", HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR), ("hIconSm", wt.HICON)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", HWND), ("message", wt.UINT), ("wParam", WPARAM),
                ("lParam", LPARAM), ("time", wt.DWORD), ("pt", wt.POINT)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", HDC), ("fErase", wt.BOOL), ("rcPaint", wt.RECT),
                ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class NMHDR(ctypes.Structure):
    _fields_ = [("hwndFrom", HWND), ("idFrom", ctypes.c_size_t), ("code", wt.UINT)]


class NMUPDOWN(ctypes.Structure):
    _fields_ = [("hdr", NMHDR), ("iPos", ctypes.c_int), ("iDelta", ctypes.c_int)]


class LVCOLUMNW(ctypes.Structure):
    _fields_ = [("mask", wt.UINT), ("fmt", ctypes.c_int), ("cx", ctypes.c_int),
                ("pszText", wt.LPWSTR), ("cchTextMax", ctypes.c_int), ("iSubItem", ctypes.c_int),
                ("iImage", ctypes.c_int), ("iOrder", ctypes.c_int), ("cxMin", ctypes.c_int),
                ("cxDefault", ctypes.c_int), ("cxIdeal", ctypes.c_int)]


class LVITEMW(ctypes.Structure):
    _fields_ = [("mask", wt.UINT), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
                ("state", wt.UINT), ("stateMask", wt.UINT), ("pszText", wt.LPWSTR),
                ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int), ("lParam", LPARAM),
                ("iIndent", ctypes.c_int), ("iGroupId", ctypes.c_int), ("cColumns", wt.UINT),
                ("puColumns", ctypes.c_void_p)]


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [("lStructSize", wt.DWORD), ("hwndOwner", HWND), ("hInstance", HINSTANCE),
                ("lpstrFilter", wt.LPCWSTR), ("lpstrCustomFilter", wt.LPWSTR),
                ("nMaxCustFilter", wt.DWORD), ("nFilterIndex", wt.DWORD),
                ("lpstrFile", wt.LPWSTR), ("nMaxFile", wt.DWORD),
                ("lpstrFileTitle", wt.LPWSTR), ("nMaxFileTitle", wt.DWORD),
                ("lpstrInitialDir", wt.LPCWSTR), ("lpstrTitle", wt.LPCWSTR),
                ("Flags", wt.DWORD), ("nFileOffset", wt.WORD), ("nFileExtension", wt.WORD),
                ("lpstrDefExt", wt.LPCWSTR), ("lCustData", LPARAM),
                ("lpfnHook", ctypes.c_void_p), ("lpTemplateName", wt.LPCWSTR),
                ("pvReserved", ctypes.c_void_p), ("dwReserved", wt.DWORD), ("FlagsEx", wt.DWORD)]


# ---- prototypes ----
user32.CreateWindowExW.restype = HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, HWND, HMENU,
                                   HINSTANCE, ctypes.c_void_p]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [HWND, wt.UINT, WPARAM, LPARAM]
user32.SendMessageW.restype = LRESULT
user32.SendMessageW.argtypes = [HWND, wt.UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = wt.BOOL
user32.PostMessageW.argtypes = [HWND, wt.UINT, WPARAM, LPARAM]
user32.SetWindowTextW.argtypes = [HWND, wt.LPCWSTR]
user32.GetWindowTextW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetClientRect.argtypes = [HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(RECT)]
user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, wt.UINT]
user32.InvalidateRect.argtypes = [HWND, ctypes.c_void_p, wt.BOOL]
user32.BeginPaint.argtypes = [HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.BeginPaint.restype = HDC
user32.EndPaint.argtypes = [HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.FillRect.argtypes = [HDC, ctypes.POINTER(RECT), HBRUSH]
user32.GetDC.restype = HDC
user32.GetDC.argtypes = [HWND]
user32.ReleaseDC.argtypes = [HWND, HDC]
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.EnableWindow.argtypes = [HWND, wt.BOOL]
user32.SetFocus.argtypes = [HWND]
user32.GetFocus.restype = HWND
user32.MessageBoxW.argtypes = [HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
user32.SetCapture.argtypes = [HWND]
user32.ReleaseCapture.argtypes = []
user32.SetTimer.argtypes = [HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [HWND, ctypes.c_size_t]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.ScreenToClient.argtypes = [HWND, ctypes.POINTER(wt.POINT)]
user32.LoadCursorW.restype = wt.HANDLE
user32.LoadCursorW.argtypes = [HINSTANCE, wt.LPCWSTR]
user32.LoadIconW.restype = wt.HICON
user32.LoadIconW.argtypes = [HINSTANCE, wt.LPCWSTR]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_void_p]
user32.GetWindowLongPtrW.restype = ctypes.c_void_p
user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [HWND, ctypes.c_int, ctypes.c_long]
user32.GetParent.argtypes = [HWND]
user32.GetParent.restype = HWND
user32.GetDlgItem.argtypes = [HWND, ctypes.c_int]
user32.GetDlgItem.restype = HWND
user32.UpdateWindow.argtypes = [HWND]
user32.SetProcessDPIAware.restype = wt.BOOL
user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]

gdi32.CreateSolidBrush.restype = HBRUSH
gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
gdi32.CreatePen.restype = HPEN
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.CreateFontW.restype = HFONT
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                              wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
gdi32.SelectObject.restype = HGDIOBJ
gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
gdi32.DeleteObject.argtypes = [HGDIOBJ]
gdi32.SetBkMode.argtypes = [HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [HDC, wt.DWORD]
gdi32.SetBkColor.argtypes = [HDC, wt.DWORD]
gdi32.RoundRect.argtypes = [HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_int]
gdi32.Rectangle.argtypes = [HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.LineTo.argtypes = [HDC, ctypes.c_int, ctypes.c_int]
gdi32.MoveToEx.argtypes = [HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.CreatePenIndirect.argtypes = [ctypes.c_void_p]
gdi32.GetStockObject.restype = HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
gdi32.SetDCBrushColor.argtypes = [HDC, wt.DWORD]
gdi32.SetDCPenColor.argtypes = [HDC, wt.DWORD]
gdi32.DCBrush = 18
gdi32.DCPen = 19
gdi32.GetDeviceCaps.argtypes = [HDC, ctypes.c_int]
gdi32.GetDeviceCaps.restype = ctypes.c_int
gdi32.SaveDC.argtypes = [HDC]
gdi32.RestoreDC.argtypes = [HDC, ctypes.c_int]
gdi32.CreateCompatibleDC.argtypes = [HDC]
gdi32.CreateCompatibleDC.restype = HDC
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [HDC, ctypes.c_int, ctypes.c_int]
gdi32.BitBlt.argtypes = [HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.DeleteDC.argtypes = [HDC]
gdi32.DeleteObject.argtypes = [HGDIOBJ]

user32.DrawTextW.argtypes = [HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(RECT), wt.UINT]
user32.DrawTextW.restype = ctypes.c_int

comctl32.InitCommonControlsEx.argtypes = [ctypes.c_void_p]
comctl32.SetWindowSubclass.argtypes = [HWND, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
comctl32.DefSubclassProc.restype = LRESULT
comctl32.DefSubclassProc.argtypes = [HWND, wt.UINT, WPARAM, LPARAM]

comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]
comdlg32.GetSaveFileNameW.argtypes = [ctypes.POINTER(OPENFILENAMEW)]

kernel32.GetModuleHandleW.restype = HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.GetLastError.restype = wt.DWORD

shell32.ShellExecuteW.argtypes = [HWND, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, wt.LPCWSTR, ctypes.c_int]


def rgb(value):
    """0xRRGGBB -> COLORREF"""
    return wt.DWORD(((value & 0xFF) << 16) | (value & 0xFF00) | ((value >> 16) & 0xFF))


def loword(v):
    return v & 0xFFFF


def hiword(v):
    return (v >> 16) & 0xFFFF


def signed_hiword(v):
    x = (v >> 16) & 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def init_common_controls():
    class INITCOMMONCONTROLSEX(ctypes.Structure):
        _fields_ = [("dwSize", wt.DWORD), ("dwICC", wt.DWORD)]
    icc = INITCOMMONCONTROLSEX(ctypes.sizeof(INITCOMMONCONTROLSEX), 0x0000FFFF)
    comctl32.InitCommonControlsEx(ctypes.byref(icc))


def set_dpi_aware():
    try:
        user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        user32.SetProcessDPIAware()


def dpi_scale(hwnd=None):
    try:
        if hwnd:
            return user32.GetDpiForWindow(hwnd) / 96.0
    except Exception:
        pass
    dc = user32.GetDC(None)
    try:
        dpi = gdi32.GetDeviceCaps(dc, 88)  # LOGPIXELSX
    finally:
        user32.ReleaseDC(None, dc)
    return (dpi or 96) / 96.0


# ---- GDI 绘图小工具 ----
class Gdi:
    """一次性 GDI 资源管理：用完统一释放。"""

    def __init__(self, hdc):
        self.hdc = hdc
        self._objs = []

    def brush(self, color):
        b = gdi32.CreateSolidBrush(rgb(color))
        self._objs.append(b)
        return b

    def pen(self, color, width=1, style=PS_SOLID):
        p = gdi32.CreatePen(style, width, rgb(color))
        self._objs.append(p)
        return p

    def font(self, face, px, weight=FW_NORMAL):
        f = gdi32.CreateFontW(-int(round(px)), 0, 0, 0, weight, 0, 0, 0,
                              DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, face)
        self._objs.append(f)
        return f

    def free(self):
        for o in self._objs:
            if o:
                gdi32.DeleteObject(o)
        self._objs = []


def fill(g, rect, color):
    hdc = g.hdc
    r = RECT(*rect)
    user32.FillRect(hdc, ctypes.byref(r), g.brush(color))


def round_fill(g, rect, radius, color, border=None, border_width=1):
    hdc = g.hdc
    l, t, r, b = rect
    if r <= l or b <= t:
        return
    old_pen = gdi32.SelectObject(hdc, g.pen(border, border_width) if border is not None
                                 else gdi32.GetStockObject(8))  # NULL_PEN; NULL_BRUSH leaves a black outline
    old_brush = gdi32.SelectObject(hdc, g.brush(color))
    gdi32.RoundRect(hdc, l, t, r, b, radius * 2, radius * 2)
    gdi32.SelectObject(hdc, old_pen)
    gdi32.SelectObject(hdc, old_brush)


def round_stroke(g, rect, radius, color, width=1):
    hdc = g.hdc
    l, t, r, b = rect
    old_pen = gdi32.SelectObject(hdc, g.pen(color, width))
    old_brush = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_BRUSH))
    gdi32.RoundRect(hdc, l, t, r, b, radius * 2, radius * 2)
    gdi32.SelectObject(hdc, old_pen)
    gdi32.SelectObject(hdc, old_brush)


def line(g, x1, y1, x2, y2, color, width=1):
    hdc = g.hdc
    old_pen = gdi32.SelectObject(hdc, g.pen(color, width))
    gdi32.MoveToEx(hdc, x1, y1, None)
    gdi32.LineTo(hdc, x2, y2)
    gdi32.SelectObject(hdc, old_pen)


def text(g, value, rect, font, color, flags=DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX):
    hdc = g.hdc
    old_font = gdi32.SelectObject(hdc, font)
    gdi32.SetBkMode(hdc, TRANSPARENT)
    gdi32.SetTextColor(hdc, rgb(color))
    r = RECT(*rect)
    user32.DrawTextW(hdc, value, -1, ctypes.byref(r), flags)
    gdi32.SelectObject(hdc, old_font)


NULL_PEN = 8
gdi32.Polygon.argtypes = [HDC, ctypes.POINTER(wt.POINT), ctypes.c_int]


def polygon(g, points, color):
    hdc = g.hdc
    array = (wt.POINT * len(points))(*[wt.POINT(int(x), int(y)) for x, y in points])
    old_pen = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_PEN))
    old_brush = gdi32.SelectObject(hdc, g.brush(color))
    gdi32.Polygon(hdc, array, len(points))
    gdi32.SelectObject(hdc, old_pen)
    gdi32.SelectObject(hdc, old_brush)


def text_width(hdc, value, font):
    old = gdi32.SelectObject(hdc, font)
    size = wt.SIZE()
    gdi32.GetTextExtentPoint32W(hdc, value, len(value), ctypes.byref(size))
    gdi32.SelectObject(hdc, old)
    return size.cx


gdi32.GetTextExtentPoint32W.argtypes = [HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.SIZE)]
