// Windows process-tree shutdown without WMI/taskkill; only used for owned roots.
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

public static class PaperAssistProcessTree
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct Entry
    {
        public uint size, usage, processId;
        public IntPtr heap;
        public uint module, threads, parentId;
        public int priority;
        public uint flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)]
        public string executable;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);
    [DllImport("kernel32.dll", EntryPoint = "Process32FirstW", SetLastError = true)]
    private static extern bool First(IntPtr snapshot, ref Entry entry);
    [DllImport("kernel32.dll", EntryPoint = "Process32NextW", SetLastError = true)]
    private static extern bool Next(IntPtr snapshot, ref Entry entry);
    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    public static void Stop(Process root)
    {
        // Cache the OS handle now. Kill/Wait operate on this process, even if its
        // numeric PID is subsequently reused. The caller verified its identity.
        IntPtr rootHandle = root.Handle;
        if (root.HasExited) return;
        DateTime observedAt = DateTime.UtcNow;
        List<Entry> entries = new List<Entry>();
        IntPtr snapshot = CreateToolhelp32Snapshot(2, 0);
        if (snapshot == new IntPtr(-1)) throw new Win32Exception();
        try
        {
            Entry entry = new Entry();
            entry.size = (uint)Marshal.SizeOf(typeof(Entry));
            if (!First(snapshot, ref entry)) throw new Win32Exception();
            do { entries.Add(entry); } while (Next(snapshot, ref entry));
        }
        finally { CloseHandle(snapshot); }

        Dictionary<int, Process> owned = new Dictionary<int, Process>();
        List<Process> children = new List<Process>();
        owned.Add(root.Id, root);
        try
        {
            bool added;
            do
            {
                added = false;
                foreach (Entry entry in entries)
                {
                    Process parent;
                    int id = (int)entry.processId;
                    if (owned.ContainsKey(id) || !owned.TryGetValue((int)entry.parentId, out parent)) continue;
                    Process child = null;
                    try
                    {
                        child = Process.GetProcessById(id);
                        IntPtr childHandle = child.Handle;
                        DateTime created = child.StartTime.ToUniversalTime();
                        if (child.HasExited || created < parent.StartTime.ToUniversalTime() || created > observedAt)
                        { child.Dispose(); continue; }
                        owned.Add(id, child);
                        children.Add(child);
                        added = true;
                    }
                    catch (ArgumentException) { if (child != null) child.Dispose(); }
                    catch (InvalidOperationException) { if (child != null) child.Dispose(); }
                }
            } while (added);

            // Drain children first: if any cannot stop, retain the managed root
            // and its state so the next stop can discover/retry the remaining tree.
            List<Exception> failures = new List<Exception>();
            for (int index = children.Count - 1; index >= 0; index--)
            {
                try { StopOne(children[index]); }
                catch (Exception error) { failures.Add(error); }
            }
            if (failures.Count > 0) throw new AggregateException("Some children could not stop; managed root retained.", failures);
            StopOne(root);
        }
        finally { foreach (Process child in children) child.Dispose(); }
    }

    private static void StopOne(Process process)
    {
        try
        {
            if (!process.HasExited) process.Kill();
            if (!process.WaitForExit(10000)) throw new TimeoutException("Process did not stop.");
        }
        catch (InvalidOperationException) { if (!process.HasExited) throw; }
        catch (Win32Exception) { if (!process.HasExited) throw; }
    }
}
