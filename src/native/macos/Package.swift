// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "VantageNative",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "VantageMac", targets: ["VantageMac"])],
    targets: [
        .target(name: "VantageCore"),
        .executableTarget(name: "VantageMac", dependencies: ["VantageCore"]),
        .testTarget(name: "VantageCoreTests", dependencies: ["VantageCore"])
    ]
)
