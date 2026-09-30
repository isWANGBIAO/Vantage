import SwiftUI
import VantageCore

@main
@MainActor
struct VantageApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = AppModel()
    var body: some Scene {
        Window("Vantage", id: "main") {
            RootView().environmentObject(model)
                .frame(minWidth: 960, minHeight: 680)
                .task {
                    delegate.model = model
                    await model.connect()
                    await NativeSmoke.runIfRequested(model)
                }
        }.defaultSize(width: 1280, height: 860)
        .commands {
            CommandGroup(replacing: .appSettings) {
                Button(model.text("设置…", "Settings…")) { model.page = .settings; showWindow() }.keyboardShortcut(",")
            }
            CommandMenu(model.text("导航", "Navigate")) {
                ForEach(Array(AppPage.allCases.enumerated()), id: \.element.id) { index, page in
                    Button(page.title(model)) { model.page = page; showWindow() }
                }
                Divider()
                Button(model.text("重新连接", "Reconnect")) { Task { await model.connect() } }.keyboardShortcut("r", modifiers: [.command, .shift])
            }
        }
        MenuBarExtra("Vantage", systemImage: "eye.circle") {
            Text(model.connected ? model.text("后端已连接", "Backend connected") : model.text("后端未连接", "Backend disconnected"))
            Button(model.text("打开 Vantage", "Open Vantage")) { showWindow() }
            Button(model.text("今日行动计划", "Today's plan")) { model.page = .plan; showWindow() }
            Button(model.text("设置", "Settings")) { model.page = .settings; showWindow() }
            Divider()
            Button(model.text("退出", "Quit")) { NSApp.terminate(nil) }.keyboardShortcut("q")
        }
    }
    private func showWindow() { NSApp.activate(ignoringOtherApps: true); NSApp.windows.first(where: { $0.identifier?.rawValue == "main" || $0.title == "Vantage" })?.makeKeyAndOrderFront(nil) }
}
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: AppModel?
    func applicationDidFinishLaunching(_ notification: Notification) {
        if let id = Bundle.main.bundleIdentifier,
           let existing = NSRunningApplication.runningApplications(withBundleIdentifier: id).first(where: { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }) {
            existing.activate(options: [.activateAllWindows]); NSApp.terminate(nil); return
        }
        NSApp.setActivationPolicy(.regular); NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ notification: Notification) { model?.shutdown() }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { sender.windows.first?.makeKeyAndOrderFront(nil) }; return true
    }
}
struct RootView: View {
    @EnvironmentObject var model: AppModel
    @State private var backendAddress = ""
    var body: some View {
        Group {
            if model.onboarding?.completed == false { OnboardingView() }
            else if model.state == nil {
                VStack(spacing: 20) {
                    Image(systemName: "eye.circle.fill").font(.system(size: 72)).foregroundStyle(.teal)
                    Text("Vantage").font(.largeTitle.bold())
                    if model.connecting { ProgressView(model.text("正在启动本地后端…", "Starting local backend…")) }
                    else {
                        Text(model.error ?? model.text("连接本地后端", "Connect to the local backend")).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        TextField("http://127.0.0.1:8000", text: $backendAddress).textFieldStyle(.roundedBorder).frame(width: 440)
                        Button(model.text("连接", "Connect")) { Task { await model.reconnect(address: backendAddress) } }.buttonStyle(.borderedProminent)
                    }
                }.padding(40).onAppear { backendAddress = model.api.address.url.absoluteString }
            } else {
                NavigationSplitView {
                    List(AppPage.allCases, selection: $model.page) { page in Label(page.title(model), systemImage: page.symbol).tag(page) }
                        .navigationSplitViewColumnWidth(min: 180, ideal: 210)
                    HStack { Circle().fill(model.connected ? Color.green : .orange).frame(width: 7, height: 7); Text(model.connected ? model.text("本机已连接", "Local · Connected") : model.text("等待重连", "Disconnected")) }.font(.caption).padding()
                } detail: {
                    Group {
                        switch model.page ?? .dashboard {
                        case .dashboard: DashboardView(); case .plan: ActionPlanView(); case .chat: ChatView()
                        case .projects: ProjectsView(); case .expenses: ExpensesView(); case .plots: PlotsView()
                        case .face: FaceView(); case .usage: UsageView(); case .logs: LogsView(); case .settings: SettingsView()
                        }
                    }.navigationTitle((model.page ?? .dashboard).title(model))
                }
            }
        }
        .alert(model.text("操作未完成", "Action could not complete"), isPresented: Binding(get: { model.error != nil && model.state != nil }, set: { if !$0 { model.error = nil } })) {
            Button("OK") { model.error = nil }
        } message: { Text(model.error ?? "") }
    }
}
