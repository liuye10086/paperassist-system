import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import useProjectSelection from './useProjectSelection';
afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.history.replaceState(null, '', '/');
});
const project = { id: 'p1', name: '研究', research_topic: '主题', project_type: 'sci', file_count: 0, created_at: '2026-10-08T00:00:00Z', updated_at: '2026-10-08T00:00:00Z', default_output_language: 'zh-CN' };
function setup(hash = '#project=p1') {
    window.history.replaceState(null, '', '/' + hash);
    vi.stubGlobal('fetch', vi.fn(async () => Response.json(project)));
    return renderHook(() => useProjectSelection(vi.fn(), vi.fn()));
}
it('retains the project instance through top level navigation and history', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.project).toBeTruthy());
    const instance = result.current.instance;
    act(() => result.current.navigateWorkspace('home'));
    expect(result.current.instance).toBe(instance);
    act(() => result.current.navigateWorkspace('projects'));
    act(() => window.history.back());
    await waitFor(() => expect(result.current.workspaceView).toBe('home'));
    act(() => window.history.back());
    await waitFor(() => expect(result.current.workspaceView).toBe('project'));
    expect(result.current.instance).toBe(instance);
});
it('guards leaving projects but not switching their views, and preserves forward after canceled back', async () => {
    const { result } = setup('#project=p2');
    act(() => result.current.open('p1'));
    await waitFor(() => expect(result.current.project).toBeTruthy());
    const guard = vi.fn(() => false);
    act(() => result.current.registerLeaveGuard(guard));
    act(() => result.current.changeSection('files'));
    expect(guard).not.toHaveBeenCalled();
    act(() => window.history.back());
    await waitFor(() => expect(result.current.section).toBe('overview'));
    act(() => window.history.back());
    await waitFor(() => expect(guard).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(window.location.hash).toBe('#project=p1'));
    expect(result.current.workspaceView).toBe('project');
    act(() => window.history.forward());
    await waitFor(() => expect(result.current.section).toBe('files'));
});
it.each(['#project=p1&project=p2', '#project=p1&section=files&task=t1', '#project=p1&section=overview&view=unknown', '#project=p1&section=reviews&round=r&reviewRevision=3'])('does not request malformed initial routes %s', hash => {
    const { result } = setup(hash);
    expect(result.current.instance).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
});
it('restores overview view and new sections', async () => {
    const { result } = setup('#project=p1&section=overview&view=settings');
    await waitFor(() => expect(result.current.project).toBeTruthy());
    expect(result.current.overviewView).toBe('settings');
    act(() => result.current.changeSection('artifacts'));
    expect(window.location.hash).toBe('#project=p1&section=artifacts');
    act(() => window.history.back());
    await waitFor(() => expect(result.current.overviewView).toBe('settings'));
});
it('uses retained project identity when opening sections and overview from home', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.project).toBeTruthy());
    act(() => result.current.navigateWorkspace('home'));
    act(() => result.current.changeSection('files'));
    expect(window.location.hash).toBe('#project=p1&section=files');
    act(() => result.current.navigateWorkspace('projects'));
    act(() => result.current.changeOverviewView('usage'));
    expect(window.location.hash).toBe('#project=p1&section=overview&view=usage');
});
it('confirms history after restoring the origin address before an accepted cross project change', async () => {
    const { result } = setup('#project=p2');
    act(() => result.current.open('p1'));
    await waitFor(() => expect(result.current.project).toBeTruthy());
    const guard = vi.fn(() => {
        expect(window.location.hash).toBe('#project=p1');
        return true;
    });
    act(() => result.current.registerLeaveGuard(guard));
    act(() => window.history.back());
    await waitFor(() => expect(result.current.instance?.id).toBe('p2'));
    expect(guard).toHaveBeenCalledTimes(1);
});
it('does not ask guards for home/projects or beforeunload unless their dirty predicate is true', async () => {
    const { result } = setup();
    await waitFor(() => expect(result.current.project).toBeTruthy());
    const guard = vi.fn(() => false);
    let dirty = false;
    act(() => result.current.registerLeaveGuard(guard, () => dirty));
    act(() => result.current.navigateWorkspace('home'));
    act(() => result.current.navigateWorkspace('projects'));
    expect(guard).not.toHaveBeenCalled();
    const clean = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    dirty = true;
    const changed = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(changed);
    expect(changed.defaultPrevented).toBe(true);
});
it.each([false, true])('restores pointers and asks once for a direct hash cross-project change accepted=%s', async (accepted) => {
    const { result } = setup();
    await waitFor(() => expect(result.current.project).toBeTruthy());
    let allow = accepted;
    const guard = vi.fn(() => {
        expect(window.location.hash).toBe('#project=p1');
        return allow;
    });
    act(() => result.current.registerLeaveGuard(guard));
    act(() => {
        window.location.hash = 'project=p2&section=files';
    });
    await waitFor(() => expect(guard).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(window.location.hash).toBe(accepted ? '#project=p2&section=files' : '#project=p1'));
    expect(result.current.instance?.id).toBe(accepted ? 'p2' : 'p1');
    if (accepted) {
        guard.mockImplementation(() => true);
        act(() => window.history.back());
        await waitFor(() => expect(result.current.instance?.id).toBe('p1'));
    }
    else {
        allow = true;
        act(() => window.history.forward());
        await waitFor(() => expect(window.location.hash).toBe('#project=p2&section=files'));
        expect(guard).toHaveBeenCalledTimes(2);
    }
});
it('retains entity navigation across home and projects history entries', async () => {
    const { result } = setup('#project=p1&section=tasks&task=t1');
    await waitFor(() => expect(result.current.project).toBeTruthy());
    act(() => result.current.navigateWorkspace('home'));
    act(() => result.current.navigateWorkspace('projects'));
    act(() => window.history.back());
    await waitFor(() => expect(result.current.workspaceView).toBe('home'));
    act(() => result.current.navigateWorkspace('project'));
    expect(result.current.section).toBe('tasks');
    expect(result.current.taskId).toBe('t1');
});
import { captureProjectAccess } from '../../shared/api/projectAccess';
it.each([
    '#project=p1&section=tasks&task=t1',
    '#project=p1&section=files&view=detail&file=f1',
    '#project=p1&section=literature&view=detail&reference=r1&search=s1',
    '#project=p1&section=literature&search=s1',
    '#project=p1&section=manuscripts&manuscript=m1&revision=3',
    '#project=p1&section=reviews&round=r1&reviewRun=run1&reviewDocument=d1',
    '#project=p1&section=reviews&reviewManuscript=m1&reviewRevision=2',
    '#project=p1&section=journals&adaptation=a1',
])('clears all entity bindings after loss of access and explicit close: %s', async (hash) => {
    const { result } = setup(hash);
    await waitFor(() => expect(result.current.project).toBeTruthy());
    const empty = () => {
        expect(result.current.instance).toBeNull();
        expect(result.current.section).toBe('overview');
        expect(result.current.taskId).toBe('');
        expect(result.current.literatureSearchId).toBe('');
        expect(result.current.resourceNavigation).toEqual({view:'list',fileId:''});
        expect(result.current.literatureNavigation).toEqual({view:'list',referenceId:''});
        expect(result.current.adaptationId).toBe('');
        expect(result.current.manuscriptLink).toEqual({ id: '', revision: 0 });
        expect(result.current.reviewLink).toEqual({ round: '', manuscript: '', revision: 0, run: '', document: '' });
    };
    act(() => captureProjectAccess('/api/v1/projects/p1').unavailable());
    empty();
    act(() => result.current.open('p1'));
    await waitFor(() => expect(result.current.project).toBeTruthy());
    act(() => {
        window.location.hash = hash;
    });
    await waitFor(() => expect(result.current.section).toBe(new URLSearchParams(hash.slice(1)).get('section')));
    act(() => result.current.close());
    empty();
    act(() => result.current.open('p2'));
    expect(result.current.taskId).toBe('');
    expect(result.current.section).toBe('overview');
    expect(result.current.manuscriptLink.id).toBe('');
    expect(result.current.reviewLink.round).toBe('');
});
