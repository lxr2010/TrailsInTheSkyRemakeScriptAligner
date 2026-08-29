import os
import ast
import json
import re
import argparse

def parse_node_value(node):
    """Recursively parse AST nodes to get their Python values."""
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Call):
        func = parse_node_value(node.func)
        args = [parse_node_value(arg) for arg in node.args]
        return { 'func': func, 'args': args }
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        operand_value = parse_node_value(node.operand)
        if isinstance(operand_value, (int, float)):
            return -operand_value
    elif isinstance(node, ast.List):
        return [parse_node_value(e) for e in node.elts]
    else:
        return ast.unparse(node)
# Check if a node is an INT(10) node
def is_newline_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'INT' and \
        node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 10

def is_int_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'INT'

def is_float_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'FLOAT'

def is_undef_node(node):
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'UNDEF' and \
        node.args and isinstance(node.args[0], ast.Constant)

def is_str_node(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)

def get_node_value(node):
    value = None
    if is_str_node(node):
        value = node.value
    else:
        value = parse_node_value(node)
        if isinstance(value,dict):
            if value['func'] in ['INT','FLOAT']:
                value = value['args'][0]
    return value

# delete all "<.+?>" stuff
def strip_special_commands(str) -> str:
    return re.sub(r'<.+?>', '', str)

def normalize_args(arg_nodes, category=None, funcid=None) -> str:
    normalized = []
    if category is not None and funcid is not None:
        normalized.append(str(category))
        normalized.append(str(funcid))
    for node in arg_nodes:
        if is_undef_node(node):
            continue
        value = get_node_value(node)
        normalized.append(str(value))
    return ",".join(normalized)



def process_arguments(arg_nodes):
    """Process a list of AST nodes to extract arguments and concatenate strings."""
    args = []
    text_parts = []

    for node in arg_nodes:
        if is_undef_node(node):
            continue

        value = get_node_value(node)
        if isinstance(value, str):
            stripped = strip_special_commands(value)
            text_parts.append(stripped)
        elif is_newline_node(node) and text_parts:
            continue
        else:
            args.append(value)
    
    if text_parts:
        args.append("".join(text_parts))

    return args

class VoiceExtractor(ast.NodeVisitor):
    """
    An AST visitor to extract specific call expressions from scena scripts.

    This visitor walks the Abstract Syntax Tree of a Python script and collects
    information about two types of function calls:
    1. Calls to 'add_struct' where the 'array2' list starts with 'INT(5)'.
    2. Calls to 'Command' where the first argument is 'Cmd_text_00' or 'Cmd_text_06'.
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.results = []
        self.current_function = None   # set_current_function 跟踪，供 RemakeFunction 列

    def visit_Call(self, node):
        # Ensure that we have a simple function call like `func(...)`
        if not isinstance(node.func, ast.Name):
            self.generic_visit(node)
            return

        func_name = node.func.id

        if func_name == 'add_struct':
            self._handle_add_struct(node)
        elif func_name == 'Command': # Changed from CallFunction
            self._handle_command(node)
        elif func_name == 'set_current_function':
            # 跟踪当前函数名（TK_/EV_/QS_/ST_…），随 Command 记录
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                self.current_function = node.args[0].value

        # Continue traversing the tree
        self.generic_visit(node)

    def _handle_add_struct(self, node):
        """Handles 'add_struct' call nodes by checking keyword arguments."""
        for kw in node.keywords:
            if kw.arg == 'array2' and isinstance(kw.value, ast.List):
                arg_list = kw.value
                # Check if the list has elements and the first one is a Call node
                if not arg_list.elts or not isinstance(arg_list.elts[0], ast.Call):
                    continue

                first_elt_call = arg_list.elts[0]
                # Check if it's a call to 'INT'
                if not isinstance(first_elt_call.func, ast.Name) or first_elt_call.func.id != 'INT':
                    continue

                # Check if the 'INT' call has arguments and the first is a Constant(5)
                if not first_elt_call.args or not isinstance(first_elt_call.args[0], ast.Constant) or first_elt_call.args[0].value != 5:
                    continue

                # Found a match, record it
                # Process the arguments in array2
                processed_args = process_arguments(arg_list.elts)

                self.results.append({
                    'file': self.file_path,
                    'line': node.lineno,
                    'column': node.col_offset,
                    'type': 'add_struct',
                    'code': ast.unparse(node),
                    'normalized_args': normalize_args(arg_list.elts),
                    'args': processed_args
                })
                # No need to check other arguments for this call
                break

    def _handle_command(self, node):
        """Handles 'Command' call nodes."""
        if not node.args:
            return

        first_arg = node.args[0]
        # Check if the first argument is a Constant string with the target value
        # Cmd_text_00/06=普通对话 13=带立绘对话(UNKNOWN_05_13 为反编译别名) 08=分支选项/系统文本
        OK_CMDS = ('Cmd_text_00', 'Cmd_text_06', 'Cmd_text_13', 'UNKNOWN_05_13', 'Cmd_text_08')
        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
            if first_arg.value in OK_CMDS:
                # The arguments for Command are in the second parameter, which is a list
                if len(node.args) > 1 and isinstance(node.args[1], ast.List):
                    arg_nodes = node.args[1].elts
                    processed_args = process_arguments(arg_nodes)
                else:
                    processed_args = []
                funcid = 13 if first_arg.value == 'UNKNOWN_05_13' else int(first_arg.value[-2:])
                if not any(isinstance(a, str) for a in processed_args):
                    return  # 无字面文本（纯 LoadVar/INT 模板，如部分 Cmd_text_08），跳过

                self.results.append({
                    'file': self.file_path,
                    'line': node.lineno,
                    'column': node.col_offset,
                    'type': 'Command',
                    'code': ast.unparse(node),
                    'normalized_args': normalize_args(arg_nodes, 0x5, funcid),
                    'command': first_arg.value,
                    'function': self.current_function,   # 所属结构函数（RemakeFunction 列）
                    'args': processed_args
                })

def parse_script(file_path):
    """Parses a single Python script and returns extracted voice data."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content, filename=file_path)
        extractor = VoiceExtractor(file_path)
        extractor.visit(tree)
        add_struct_map = { a['normalized_args']: a for a in extractor.results if a['type'] == 'add_struct'}
        command_map = {c['normalized_args']: c for c in extractor.results if c['type'] == 'Command'}

        for a in extractor.results :
            if a['type'] == 'add_struct':
                if a['normalized_args'] in command_map.keys():
                    a['line_corr'] = command_map[a['normalized_args']]['line']
            elif a['type'] == 'Command':
                if a['normalized_args'] in add_struct_map.keys():
                    a['line_corr'] = add_struct_map[a['normalized_args']]['line']
        return extractor.results
    except Exception as e:      
        print(f"Error parsing {file_path}: {e}")
        raise e
        return []

def process_directory(directory, lang, output_dir):
    """Parse all .py files in a directory and write scena_data_{lang}*.json."""
    if not os.path.isdir(directory):
        print(f"Warning: Directory not found, skipping: {directory}")
        return 0

    print(f"Scanning directory: {directory}...")
    lang_results = []
    for filename in sorted(os.listdir(directory)):
        if filename.endswith('.py'):
            file_path = os.path.join(directory, filename)
            results = parse_script(file_path)
            if results:
                lang_results.extend(results)

    lang_results.sort(key=lambda x: (x['file'], x['line']))

    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f'scena_data_{lang}.json')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(lang_results, f, indent=4, ensure_ascii=False)

    for typ in ["Command", "add_struct"]:
        output_file_typ = os.path.join(output_dir, f'scena_data_{lang}_{typ}.json')
        lang_results_typ = [r for r in lang_results if r['type'] == typ]
        with open(output_file_typ, 'w', encoding='utf-8') as f:
            json.dump(lang_results_typ, f, indent=4, ensure_ascii=False)

    print(f"Found {len(lang_results)} entries for '{lang}'. Results saved to {output_file}")
    return len(lang_results)


def main():
    """Main function to find scripts, parse them, and save the results."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="Extract Cmd_text_00/06 from KuroTools-decompiled .py scena files.")
    parser.add_argument("--input-dir", help="Directory containing decompiled .py scena files (single language)")
    parser.add_argument("--language", choices=["jp", "sc"], help="Language tag for output naming (required with --input-dir)")
    parser.add_argument("--output-dir", default=base_dir, help="Output directory for scena_data_*.json")
    args = parser.parse_args()

    if args.input_dir:
        if not args.language:
            raise SystemExit("--language is required when --input-dir is provided")
        total_entries = process_directory(args.input_dir, args.language, args.output_dir)
        print(f"\nExtraction complete. Found a total of {total_entries} entries.")
        return

    # 默认行为：扫描脚本目录下的 scena/jp 和 scena/sc
    scena_dirs = {
        'jp': os.path.join(base_dir, 'scena', 'jp'),
        'sc': os.path.join(base_dir, 'scena', 'sc')
    }

    total_entries = 0
    for lang, directory in scena_dirs.items():
        total_entries += process_directory(directory, lang, base_dir)

    print(f"\nExtraction complete. Found a total of {total_entries} entries.")

if __name__ == '__main__':
    main()
