# pylint: disable-all
import os
import time
import logging
from typing import Set, List, Dict, Tuple
from pathlib import Path

class PathManager:
    supported_pt_extensions: Set[str] = {".ckpt", ".pt", ".bin", ".pth", ".safetensors", ".pkl"}
    folder_names_and_paths: Dict[str, Tuple[List[str], Set[str]]] = {}
    filename_list_cache: Dict[str, Tuple[List[str], Dict[str, float], float]] = {}

    def __init__(self):
        self.base_path = os.path.dirname(os.path.realpath(__file__))
        self.models_dir = os.path.join(self.base_path, "models")
        self.output_directory = os.path.join(self.base_path, "output")
        self.temp_directory = os.path.join(self.base_path, "temp")
        self.input_directory = os.path.join(self.base_path, "input")
        self.user_directory = os.path.join(self.base_path, "user")

        self._initialize_folder_paths()

    def _initialize_folder_paths(self):
        """初始化文件夹路径"""
        folders = [
            ("checkpoints", "checkpoints", self.supported_pt_extensions),
            ("configs", "configs", {".yaml"}),
            ("loras", "loras", self.supported_pt_extensions),
            ("vae", "vae", self.supported_pt_extensions),
            ("clip", "clip", self.supported_pt_extensions),
            ("unet", "unet", self.supported_pt_extensions),
            ("clip_vision", "clip_vision", self.supported_pt_extensions),
            ("style_models", "style_models", self.supported_pt_extensions),
            ("embeddings", "embeddings", self.supported_pt_extensions),
            ("diffusers", "diffusers", {"folder"}),
            ("vae_approx", "vae_approx", self.supported_pt_extensions),
            ("controlnet", "controlnet", self.supported_pt_extensions),
            ("gligen", "gligen", self.supported_pt_extensions),
            ("upscale_models", "upscale_models", self.supported_pt_extensions),
            ("custom_nodes", "custom_nodes", set()),
            ("hypernetworks", "hypernetworks", self.supported_pt_extensions),
            ("photomaker", "photomaker", self.supported_pt_extensions),
            ("classifiers", "classifiers", {""}),
        ]

        for folder_name, subfolder, extensions in folders:
            self.folder_names_and_paths[folder_name] = (
                [os.path.join(self.models_dir, subfolder)],
                extensions
            )

        # 特殊情况处理
        self.folder_names_and_paths["controlnet"][0].append(os.path.join(self.models_dir, "t2i_adapter"))
        self.folder_names_and_paths["custom_nodes"] = ([os.path.join(self.base_path, "custom_nodes")], set())

    def get_secure_absolute_path(self, relative_path):
        """获取安全的绝对路径，并确保目录存在且具有适当的权限。"""
        abs_path = os.path.abspath(os.path.join(self.base_path, relative_path))
        Path(os.path.dirname(abs_path)).mkdir(parents=True, exist_ok=True)

        try:
            if not os.path.exists(abs_path):
                os.makedirs(abs_path, mode=0o755)
            else:
                os.chmod(abs_path, 0o755)
        except PermissionError:
            temp_dir = os.path.join(self.temp_directory, 'fallback_' + os.path.basename(relative_path))
            os.makedirs(temp_dir, exist_ok=True)
            abs_path = temp_dir
            logging.warning(f"使用临时目录处理权限问题：{abs_path}")

        logging.info(f"绝对路径设置为：{abs_path}")
        return abs_path

    def set_output_directory(self, output_dir: str):
        """设置输出目录路径。"""
        self.output_directory = output_dir

    def set_temp_directory(self, temp_dir: str):
        """设置临时目录路径。"""
        self.temp_directory = temp_dir

    def set_input_directory(self, input_dir: str):
        """设置输入目录路径。"""
        self.input_directory = input_dir

    def get_output_directory(self) -> str:
        """获取输出目录路径。"""
        return self.output_directory

    def get_temp_directory(self) -> str:
        """获取临时目录路径。"""
        return self.temp_directory

    def get_input_directory(self) -> str:
        """获取输入目录路径。"""
        return self.input_directory

    def get_directory_by_type(self, type_name: str) -> str:
        """根据类型名称获取目录路径。"""
        if type_name == "output":
            return self.get_output_directory()
        if type_name == "temp":
            return self.get_temp_directory()
        if type_name == "input":
            return self.get_input_directory()
        raise ValueError(f"未知的类型名称: {type_name}")

    def annotated_filepath(self, name: str) -> Tuple[str, str]:
        """根据注释确定文件路径。"""
        if name.endswith("[output]"):
            base_dir = self.get_output_directory()
            name = name[:-9]
        elif name.endswith("[input]"):
            base_dir = self.get_input_directory()
            name = name[:-8]
        elif name.endswith("[temp]"):
            base_dir = self.get_temp_directory()
            name = name[:-7]
        else:
            base_dir = self.get_input_directory()
        return name, base_dir

    def get_annotated_filepath(self, name: str, default_dir: str = "") -> str:
        """获取注释文件路径。"""
        name, base_dir = self.annotated_filepath(name)
        if base_dir is None:
            base_dir = default_dir if default_dir else self.get_input_directory()
        return os.path.join(base_dir, name)

    def exists_annotated_filepath(self, name: str) -> bool:
        """检查注释文件路径是否存在。"""
        name, base_dir = self.annotated_filepath(name)
        filepath = os.path.join(base_dir, name)
        return os.path.exists(filepath)

    def add_model_folder_path(self, folder_name: str, full_folder_path: str):
        """添加模型文件夹路径。"""
        if folder_name in self.folder_names_and_paths:
            self.folder_names_and_paths[folder_name][0].append(full_folder_path)
        else:
            self.folder_names_and_paths[folder_name] = ([full_folder_path], set())

    def get_folder_paths(self, folder_name: str) -> List[str]:
        """获取文件夹路径。"""
        if folder_name not in self.folder_names_and_paths:
            raise ValueError(f"未知的文件夹名称: {folder_name}")
        return self.folder_names_and_paths[folder_name][0][:]

    def recursive_search(self, directory: str, excluded_dir_names: List[str] = None) -> Tuple[List[str], Dict[str, float]]:
        """递归搜索目录中的文件。"""
        if not os.path.isdir(directory):
            return [], {}

        excluded_dir_names = excluded_dir_names or []
        result = []
        dirs = {}

        try:
            dirs[directory] = os.path.getmtime(directory)
        except FileNotFoundError:
            logging.warning(f"警告: 无法访问 {directory}。跳过此路径。")

        for dirpath, subdirs, filenames in os.walk(directory, followlinks=True, topdown=True):
            subdirs[:] = [d for d in subdirs if d not in excluded_dir_names]
            for file_name in filenames:
                relative_path = os.path.relpath(os.path.join(dirpath, file_name), directory)
                result.append(relative_path)

            for d in subdirs:
                path = os.path.join(dirpath, d)
                try:
                    dirs[path] = os.path.getmtime(path)
                except FileNotFoundError:
                    logging.warning(f"警告: 无法访问 {path}。跳过此路径。")

        return result, dirs

    def filter_files_extensions(self, files: List[str], extensions: Set[str]) -> List[str]:
        """按扩展名过滤文件。"""
        return sorted(list(filter(lambda a: os.path.splitext(a)[-1].lower() in extensions or len(extensions) == 0, files)))

    def get_full_path(self, folder_name: str, filename: str) -> str:
        """获取完整文件路径。"""
        if folder_name not in self.folder_names_and_paths:
            raise ValueError(f"未知的文件夹名称: {folder_name}")
        folders = self.folder_names_and_paths[folder_name]
        filename = os.path.relpath(os.path.join("/", filename), "/")
        for x in folders[0]:
            full_path = os.path.join(x, filename)
            if os.path.isfile(full_path):
                return full_path
            elif os.path.islink(full_path):
                logging.warning(f"警告: 路径 {full_path} 存在但不链接到任何地方，跳过。")
        return ""

    def get_filename_list(self, folder_name: str) -> List[str]:
        """获取文件名称列表。"""
        out = self._cached_filename_list(folder_name)
        if not out[0]:
            out = self._get_filename_list(folder_name)
            self.filename_list_cache[folder_name] = out
        return list(out[0])

    def _get_filename_list(self, folder_name: str) -> Tuple[List[str], Dict[str, float], float]:
        """获取文件名称列表（内部方法）。"""
        output_list = set()
        folders = self.folder_names_and_paths[folder_name]
        output_folders = {}
        for x in folders[0]:
            files, folders_all = self.recursive_search(x, excluded_dir_names=[".git"])
            output_list.update(self.filter_files_extensions(files, folders[1]))
            output_folders.update(folders_all)
        return (sorted(list(output_list)), output_folders, time.perf_counter())

    def _cached_filename_list(self, folder_name: str) -> Tuple[List[str], Dict[str, float], float]:
        """获取缓存的文件名称列表（内部方法）。"""
        if folder_name not in self.filename_list_cache:
            return ([], {}, 0.0)
        out = self.filename_list_cache[folder_name]

        for x, time_modified in out[1].items():
            if os.path.getmtime(x) != time_modified:
                return ([], {}, 0.0)

        folders = self.folder_names_and_paths[folder_name]
        for x in folders[0]:
            if os.path.isdir(x) and x not in out[1]:
                return ([], {}, 0.0)

        return out

    def get_save_image_path(self, filename_prefix: str, output_dir: str, image_width: int = 0, image_height: int = 0) -> Tuple[str, str, int, str, str]:
        """获取保存图像的路径。"""
        def map_filename(filename: str) -> Tuple[int, str]:
            prefix_len = len(os.path.basename(filename_prefix))
            prefix = filename[: prefix_len + 1]
            try:
                digits = int(filename[prefix_len + 1 :].split("_")[0])
            except Exception:
                digits = 0
            return (digits, prefix)

        def compute_vars(input: str, image_width: int, image_height: int) -> str:
            input = input.replace("%width%", str(image_width))
            input = input.replace("%height%", str(image_height))
            return input

        filename_prefix = compute_vars(filename_prefix, image_width, image_height)
        subfolder = os.path.dirname(os.path.normpath(filename_prefix))
        filename = os.path.basename(os.path.normpath(filename_prefix))
        full_output_folder = os.path.join(output_dir, subfolder)

        if os.path.commonpath((output_dir, os.path.abspath(full_output_folder))) != output_dir:
            err = (
                "**** 错误: 不允许在输出文件夹外保存图像。"
                + "\n full_output_folder: "
                + os.path.abspath(full_output_folder)
                + "\n output_dir: "
                + output_dir
                + "\n commonpath: "
                + os.path.commonpath((output_dir, os.path.abspath(full_output_folder)))
            )
            logging.error(err)
            raise Exception(err)

        try:
            counter = max(filter(lambda a: os.path.normcase(a[1][:-1]) == os.path.normcase(filename) and a[1][-1] == "_",
                                 map(map_filename, os.listdir(full_output_folder))))[0] + 1
        except ValueError:
            counter = 1
        except FileNotFoundError:
            os.makedirs(full_output_folder, exist_ok=True)
            counter = 1

        return full_output_folder, filename, counter, subfolder, filename_prefix
