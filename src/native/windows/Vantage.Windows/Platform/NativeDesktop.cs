using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using Microsoft.UI.Xaml;
using Microsoft.Win32;
using Windows.ApplicationModel.DataTransfer;
using Windows.Storage.Pickers;
namespace Vantage.Windows.Platform;

public static class NativeDesktop
{
    public static string Locale => CultureInfo.CurrentUICulture.Name;
    public static void Copy(string text) { var package = new DataPackage(); package.SetText(text); Clipboard.SetContent(package); }
    public static void SetStartup(bool enabled)
    {
        using var key = Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        if (enabled) key.SetValue("Vantage.Native", $"\"{Environment.ProcessPath}\" --background");
        else key.DeleteValue("Vantage.Native", false);
    }
    public static bool StartupEnabled()
    {
        using var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Run");
        return key?.GetValue("Vantage.Native") is string;
    }
    public static void OpenPath(string path)
    {
        if (!Path.IsPathFullyQualified(path) || !Directory.Exists(path)) throw new IOException("The selected runtime folder does not exist.");
        Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
    }
    public static async Task<string?> PickFolderAsync(Window window)
    {
        var picker = new FolderPicker(); picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(window));
        return (await picker.PickSingleFolderAsync())?.Path;
    }
    public static async Task<string?> PickAudioAsync(Window window)
    {
        var picker = new FileOpenPicker(); foreach (var ext in new[] { ".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac" }) picker.FileTypeFilter.Add(ext);
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(window));
        return (await picker.PickSingleFileAsync())?.Path;
    }
    public static async Task<string?> PickSaveAsync(Window window, string name, string extension)
    {
        var picker = new FileSavePicker { SuggestedFileName = name };
        picker.FileTypeChoices.Add(extension.ToUpperInvariant(), new List<string> { extension });
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(window));
        return (await picker.PickSaveFileAsync())?.Path;
    }
    public static void PermissionSettings(string kind)
    {
        if (kind is not ("webcam" or "microphone" or "location")) throw new ArgumentException("Unknown permission.");
        Process.Start(new ProcessStartInfo($"ms-settings:privacy-{kind}") { UseShellExecute = true });
    }
    public static void ActivateExisting() { var hwnd = FindWindow(null, "Vantage"); if (hwnd != IntPtr.Zero) { ShowWindow(hwnd, 9); SetForegroundWindow(hwnd); } }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr FindWindow(string? cls, string title);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr hwnd, int command);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr hwnd);
}

public sealed class TrayIcon : IDisposable
{
    const uint CallbackMessage = 0x8001;
    readonly IntPtr hwnd; readonly Action show; readonly Action quit; readonly SubclassProc callback; readonly uint taskbarCreated;
    NotifyData data;
    public string ShowLabel { get; set; } = "打开 Vantage";
    public string ExitLabel { get; set; } = "退出";
    public TrayIcon(Window window, Action showWindow, Action exit)
    {
        hwnd = WinRT.Interop.WindowNative.GetWindowHandle(window); show = showWindow; quit = exit; callback = WindowProc;
        taskbarCreated = RegisterWindowMessage("TaskbarCreated");
        data = new NotifyData { Size = (uint)Marshal.SizeOf<NotifyData>(), Window = hwnd, Id = 1, Flags = 1 | 2 | 4,
            Callback = CallbackMessage, Icon = LoadImage(IntPtr.Zero, Path.Combine(AppContext.BaseDirectory, "Assets", "Vantage.ico"), 1, 32, 32, 0x10), Tip = "Vantage", Info = "", InfoTitle = "" };
        if (data.Icon == IntPtr.Zero) data.Icon = LoadIcon(IntPtr.Zero, new IntPtr(32512));
        SetWindowSubclass(hwnd, callback, 1, 0); Shell_NotifyIcon(0, ref data);
    }
    IntPtr WindowProc(IntPtr window, uint message, UIntPtr wParam, IntPtr lParam, UIntPtr id, UIntPtr reference)
    {
        if (message == taskbarCreated) Shell_NotifyIcon(0, ref data);
        if (message == CallbackMessage)
        {
            var code = (uint)lParam.ToInt64();
            if (code == 0x0203) show();
            if (code == 0x0205)
            {
                GetCursorPos(out var point); var menu = CreatePopupMenu();
                AppendMenu(menu, 0, 1, ShowLabel); AppendMenu(menu, 0, 2, ExitLabel); SetForegroundWindow(hwnd);
                var chosen = TrackPopupMenu(menu, 0x0100 | 0x0002, point.X, point.Y, 0, hwnd, IntPtr.Zero); DestroyMenu(menu);
                if (chosen == 1) show(); else if (chosen == 2) quit();
            }
        }
        return DefSubclassProc(window, message, wParam, lParam);
    }
    public void Dispose() { Shell_NotifyIcon(2, ref data); RemoveWindowSubclass(hwnd, callback, 1); }
    delegate IntPtr SubclassProc(IntPtr hwnd, uint msg, UIntPtr wParam, IntPtr lParam, UIntPtr id, UIntPtr reference);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct NotifyData
    {
        public uint Size; public IntPtr Window; public uint Id; public uint Flags; public uint Callback; public IntPtr Icon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Tip;
        public uint State; public uint StateMask;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string Info;
        public uint Timeout;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string InfoTitle;
        public uint InfoFlags; public Guid Guid; public IntPtr BalloonIcon;
    }
    [StructLayout(LayoutKind.Sequential)] struct Point { public int X; public int Y; }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)] static extern bool Shell_NotifyIcon(uint action, ref NotifyData data);
    [DllImport("comctl32.dll")] static extern bool SetWindowSubclass(IntPtr window, SubclassProc proc, uint id, uint data);
    [DllImport("comctl32.dll")] static extern bool RemoveWindowSubclass(IntPtr window, SubclassProc proc, uint id);
    [DllImport("comctl32.dll")] static extern IntPtr DefSubclassProc(IntPtr window, uint message, UIntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern uint RegisterWindowMessage(string message);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern IntPtr LoadImage(IntPtr instance, string name, uint type, int cx, int cy, uint flags);
    [DllImport("user32.dll")] static extern IntPtr LoadIcon(IntPtr instance, IntPtr name);
    [DllImport("user32.dll")] static extern bool GetCursorPos(out Point point);
    [DllImport("user32.dll")] static extern IntPtr CreatePopupMenu();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool AppendMenu(IntPtr menu, uint flags, uint id, string text);
    [DllImport("user32.dll")] static extern uint TrackPopupMenu(IntPtr menu, uint flags, int x, int y, int reserved, IntPtr window, IntPtr rect);
    [DllImport("user32.dll")] static extern bool DestroyMenu(IntPtr menu);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
}
