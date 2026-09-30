import Foundation

public enum MarkdownBlock: Equatable, Sendable {
    case paragraph(String)
    case heading(String, Int)
    case code(String, String)
    case table([String], [[String]])
    case quote(String)
}
public enum MarkdownBlocks {
    public static func parse(_ text: String) -> [MarkdownBlock] {
        let lines = text.components(separatedBy: .newlines)
        var result: [MarkdownBlock] = []; var index = 0
        while index < lines.count {
            let line = lines[index]
            if line.hasPrefix("```") || line.hasPrefix("~~~") {
                let fence = String(line.prefix(3)); let language = String(line.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                index += 1; var code: [String] = []
                while index < lines.count && !lines[index].hasPrefix(fence) { code.append(lines[index]); index += 1 }
                result.append(.code(language, code.joined(separator: "\n")))
                if index < lines.count { index += 1 }; continue
            }
            if index + 1 < lines.count, line.contains("|"), isTableSeparator(lines[index + 1]) {
                let headers = cells(line); index += 2; var rows: [[String]] = []
                while index < lines.count && lines[index].contains("|") && !lines[index].isEmpty { rows.append(cells(lines[index])); index += 1 }
                result.append(.table(headers, rows)); continue
            }
            let heading = line.prefix(while: { $0 == "#" }).count
            if (1...6).contains(heading), line.dropFirst(heading).first == " " { result.append(.heading(String(line.dropFirst(heading + 1)), heading)) }
            else if line.hasPrefix("> ") { result.append(.quote(String(line.dropFirst(2)))) }
            else { result.append(.paragraph(line)) }
            index += 1
        }
        return result
    }
    private static func cells(_ line: String) -> [String] {
        var value = line.trimmingCharacters(in: .whitespaces)
        if value.hasPrefix("|") { value.removeFirst() }; if value.hasSuffix("|") { value.removeLast() }
        // Escaped pipes are content, not column boundaries.
        let placeholder = "\u{001f}"
        return value.replacingOccurrences(of: "\\|", with: placeholder).components(separatedBy: "|").map { $0.replacingOccurrences(of: placeholder, with: "|").trimmingCharacters(in: .whitespaces) }
    }
    private static func isTableSeparator(_ line: String) -> Bool {
        let values = cells(line)
        return !values.isEmpty && values.allSatisfy { cell in
            let stripped = cell.replacingOccurrences(of: ":", with: "").trimmingCharacters(in: .whitespaces)
            return stripped.count >= 3 && stripped.allSatisfy { $0 == "-" }
        }
    }
}
