using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Windows.Forms;

internal static class Launcher
{
    [STAThread]
    private static int Main(string[] args)
    {
        string projectDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string applicationPath = Path.Combine(projectDirectory, "app.py");
        if (!File.Exists(applicationPath))
        {
            MessageBox.Show(
                "app.py를 찾지 못했습니다. run.exe를 프로그램 폴더 안에서 실행하십시오.",
                "Vernier 스펙트럼 분석기",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 2;
        }

        string pythonWindowed = FindPythonWindowed();
        if (pythonWindowed == null)
        {
            MessageBox.Show(
                "pythonw.exe를 찾지 못했습니다. Python을 설치하고 PATH에 추가하십시오.",
                "Vernier 스펙트럼 분석기",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 3;
        }

        var arguments = new List<string> { applicationPath };
        arguments.AddRange(args);
        var startInfo = new ProcessStartInfo
        {
            FileName = pythonWindowed,
            Arguments = string.Join(" ", arguments.Select(QuoteArgument)),
            WorkingDirectory = projectDirectory,
            UseShellExecute = false,
            CreateNoWindow = true
        };
        startInfo.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";

        try
        {
            Process process = Process.Start(startInfo);
            if (process == null)
            {
                throw new InvalidOperationException("Python 프로세스를 시작하지 못했습니다.");
            }

            if (args.Any(argument => argument == "--smoke-test"))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
            return 0;
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                "프로그램을 실행하지 못했습니다.\n\n" + exception.Message,
                "Vernier 스펙트럼 분석기",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 4;
        }
    }

    private static string FindPythonWindowed()
    {
        var candidates = new List<string>();
        string userProfile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        candidates.Add(Path.Combine(userProfile, "anaconda3", "pythonw.exe"));
        candidates.Add(Path.Combine(userProfile, "miniconda3", "pythonw.exe"));

        string pathValue = Environment.GetEnvironmentVariable("PATH") ?? string.Empty;
        foreach (string directory in pathValue.Split(Path.PathSeparator))
        {
            if (!string.IsNullOrWhiteSpace(directory))
            {
                try
                {
                    candidates.Add(Path.Combine(directory.Trim(), "pythonw.exe"));
                }
                catch (ArgumentException)
                {
                    // Ignore malformed PATH entries and continue searching.
                }
            }
        }

        return candidates.FirstOrDefault(File.Exists);
    }

    private static string QuoteArgument(string argument)
    {
        if (argument.Length > 0 && argument.All(character => !char.IsWhiteSpace(character) && character != '"'))
        {
            return argument;
        }

        var result = new StringBuilder("\"");
        int backslashes = 0;
        foreach (char character in argument)
        {
            if (character == '\\')
            {
                backslashes++;
            }
            else if (character == '"')
            {
                result.Append('\\', backslashes * 2 + 1);
                result.Append('"');
                backslashes = 0;
            }
            else
            {
                result.Append('\\', backslashes);
                result.Append(character);
                backslashes = 0;
            }
        }
        result.Append('\\', backslashes * 2);
        result.Append('"');
        return result.ToString();
    }
}
