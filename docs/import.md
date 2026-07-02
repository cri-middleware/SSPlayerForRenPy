# Asset Import

SpriteStudio Player for Ren'Py does not read SpriteStudio project files (`.sspj`) directly; instead, they are converted into a binary format for Ren'Py (`.ssab`) before use. We provide two conversion methods to suit your project's scale and workflow.

```mermaid
graph LR
    SS[" .sspj / Images<br>(Source Assets) "]

    subgraph Convert ["Conversion Process"]
        AUTO[[" Auto Importer<br>(On Ren'Py Startup) "]]
        GUI[[" SSConverterGUI<br>(GUI App) "]]
        CLI[[" ssconverter-cli<br>(CLI Tool) "]]
        WEB[[" ssconverter-web<br>(Web Browser) "]]
    end

    subgraph RenPy ["Ren'Py Project (game/)"]
        BIN[" .ssab + Textures "]
        NODE[[ SSPlayer ]]
        RT(" libssruntime ")
    end

    SS -- "Place in SpriteStudio_Source/" --> AUTO
    SS -- "Drag & Drop" --> GUI
    SS -- "CLI / CI" --> CLI
    SS -- "Drop in Browser" --> WEB
    AUTO -. "Auto-Generate" .-> BIN
    GUI -. "Manual Deploy" .-> BIN
    CLI -. "Manual Deploy" .-> BIN
    WEB -. "Unzip & Deploy" .-> BIN
    
    BIN -- "Referenced in Script" --> NODE
    NODE -. "Load Binary" .-> RT

    classDef generated stroke-dasharray: 5 5;
    class BIN generated;
```

---

## Method 1: Auto Importer

This feature automatically detects updates to `.sspj` files when Ren'Py starts, runs the conversion behind the scenes, and imports them into your game. It is recommended for quick iterations (adjustments and verification) as it eliminates the hassle of manual conversion.

> [!WARNING]
> This feature only works **when Ren'Py is launched in developer mode (`config.developer = True`)**. The conversion process will not run in release builds meant for players.

### Basic Usage

1. Create a folder named **`SpriteStudio_Source`** in the root directory of your game project (at the same level as the `game/` folder).
2. Inside the created `SpriteStudio_Source` folder, place the entire project dataset (`.sspj`, `.ssae`, images, etc.) created in SpriteStudio.
3. Launch or reload (`Shift + R`) your Ren'Py project.

**Result:**
If a file update is detected during the startup initialization phase, the conversion will run automatically, and a folder with the same name as the project will be generated under **`game/ss_assets/`**.
(Example: If you placed `SpriteStudio_Source/Hero/Hero.sspj`, the converted data will be output to `game/ss_assets/Hero/`.)

> [!TIP]
> **Customizing Output Paths**
> If you want to change the source location or output destination path, you can override them by defining variables on the Ren'Py script side.
> ```renpy
> # Example: Define this in options.rpy or similar, before the auto-importer (init -10)
> define -15 ss_source_dir = "my_custom_source_folder"
> define -15 ss_output_dir = "game/my_converted_assets"
> ```

---

## Method 2: Manual Conversion via Standalone GUI Tool (`SSConverterGUI`)

If you are not familiar with command-line operations or prefer to convert files easily using drag-and-drop, we recommend using the dedicated desktop application **`SSConverterGUI`**.

### Download and Usage

1. Download and launch the latest version suitable for your OS from the [SSConverterGUI Releases page](https://github.com/cri-middleware/SSConverterGUI/releases).
2. Directly **drag and drop** the `.sspj` file or a folder containing `.sspj` files into the designated area of the application window.
3. (Optional) Specify the output directory and press the "Convert" button to generate the `.ssab` files all at once.
4. After conversion, manually move the output folder into your Ren'Py project's `game/` directory (e.g., `game/ss_assets/Hero/`).

> [!NOTE]
> It is extremely easy to use, as dropping a folder automatically finds and batch-converts all `.sspj` files inside it.

---

## Method 3: CLI / CI using CLI Converter (`ssconverter-cli`)

For automated builds in CI/CD (Continuous Integration) or batch processing across large-scale projects, we recommend using the independent execution tool **`ssconverter-cli`**. This tool, which is also commonly used for Godot and Unity, allows you to perform conversions directly from the command line without needing Python or Ren'Py execution environments.

### How to Download

From the [SpriteStudio-SDK Releases page](https://github.com/cri-middleware/SpriteStudio-SDK/releases), download the `ssconverter-cli` executable suitable for your OS (e.g., a ZIP containing `ssconverter-cli.exe` for Windows) and extract it to a folder of your choice.

> [!NOTE]
> The `ssconverter-cli` binary is not bundled with SpriteStudio Player for Ren'Py. If you wish to use the CLI, please obtain it separately from the SDK repository.

### Basic Usage

Open your terminal (Command Prompt or bash script) and execute the following command. The simplest way is to specify just the input file without the `-o` option.

```bash
# Basic Syntax
ssconverter-cli <path_to_input.sspj>

# Execution Example
ssconverter-cli SpriteStudio_Source/Hero/Hero.sspj
```

- Executing the above generates a folder with the same name as the project (e.g., `Hero/`) in the same directory as the `.sspj` file, and outputs the `.ssab` and image files inside it.
- After conversion, manually move and place the generated folder into your Ren'Py project's `game/` directory (e.g., `game/ss_assets/Hero/`).
- *If you want to output directly to an arbitrary location, you can use the `-o <output_directory_path>` option.*

### Batch Processing via Directory Specification

By specifying a directory path instead of a file, it will automatically find all `.sspj` projects within that directory and convert them all at once.

```bash
# Batch convert all projects under the specified folder
ssconverter-cli SpriteStudio_Source/
```
This is very convenient when you want to convert and update animation data for multiple characters or scenes in one go.

---

## Method 4: Web-based Converter (`ssconverter-web`)

If you want to try conversion quickly in your browser without installing any tools, you can use **`ssconverter-web`**, which is included in the sister project `SSPlayerForWeb`.

- It uses WebAssembly to process files locally within the browser, meaning your files are never uploaded to an external server.
- Simply drag and drop the `.sspj` and related files (like images) into the browser window. The converted result will be **downloaded as a `.zip` file**.
- Unzip the downloaded `.zip` file, and place the generated `.ssab` and images together in your `game/` folder.

For details, please refer to the documentation in the [SSPlayerForWeb repository](https://github.com/cri-middleware/SSPlayerForWeb).

---

## Release Builds and Archives (`.rpa`)

Because `.ssab` files and textures (PNG / WebP) are loaded via Ren'Py's loader, **they can be successfully loaded even if included in an `.rpa` archive**. Textures go through Ren'Py's standard image pipeline (`Image`), so any format Ren'Py supports — PNG or WebP — works just like every other image in your project.
When archiving `game/` for distribution builds (e.g., via `build.classify`), you may simply leave them to be archived. They will also work properly if left as loose files.
