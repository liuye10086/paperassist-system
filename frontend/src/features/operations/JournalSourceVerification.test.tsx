import {cleanup,render,screen} from '@testing-library/react'
import {afterEach,expect,it} from 'vitest'
import JournalSourceVerification from './JournalSourceVerification'
import {setLocale} from '../../shared/i18n'
afterEach(()=>{cleanup();setLocale('zh-CN')})
it('keeps null verification unknown and synthetic provenance visible, and renders an actual source date in English',()=>{setLocale('en');render(<JournalSourceVerification sources={[{id:'synthetic',verified_on:null,verification_scope:'synthetic_material_only',official_verification:'not_established'},{id:'official_local',verified_on:'2026-10-20',verification_scope:'local_source_record_only',official_verification:'not_established'}]}/>);expect(screen.getByText('Verification time unknown; official verification has not been established.')).toBeTruthy();expect(screen.getByText(/Synthetic material only/)).toBeTruthy();expect(screen.getByText('2026-10-20')).toBeTruthy();expect(screen.getAllByText('Local manual source; this does not establish online verification.')).toHaveLength(2)})
