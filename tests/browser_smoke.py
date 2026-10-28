"""Optional Playwright + installed Chrome E2E. Controls the running demo instance."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8875')
    parser.add_argument('--chrome',default='/opt/google/chrome/chrome');args=parser.parse_args()
    result={};errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=args.chrome,headless=True)
        context=browser.new_context(viewport={'width':1500,'height':1300})
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(args.url);expect(page.locator('#connection')).to_contain_text('online')
        page.locator('#reset').click();expect(page.locator('#mode')).to_have_text('stopped')
        for name,value in {'green_ns':'5','green_ew':'40','desired_speed':'50','simulation_speed':'5',
                           'demand_north':'600','demand_east':'900'}.items():
            page.locator(f'[name="{name}"]').fill(value)
        page.locator('#apply').click();expect(page.locator('#applied')).to_contain_text('Applied')
        state=page.request.get(args.url+'/api/state').json()
        assert state['parameters']['green_ns']==5 and state['parameters']['green_ew']==40
        assert state['parameters']['demand_east']==900
        result['websocket_parameters_reach_engine']=True
        page.locator('#start').click();expect(page.locator('#mode')).to_have_text('running')
        page.wait_for_function("document.getElementById('phase').textContent==='E GREEN'",timeout=12000)
        state=page.request.get(args.url+'/api/state').json()
        assert state['signals']['groups']['E']=='GREEN' and state['signals']['groups']['N']=='RED'
        assert any(v['distance_to_stop']<0 for v in state['vehicles'].values())
        result['changed_timings_release_moving_traffic']=True
        page.locator('#pause').click();expect(page.locator('#mode')).to_have_text('paused')
        frozen=page.request.get(args.url+'/api/state').json();page.wait_for_timeout(350)
        after=page.request.get(args.url+'/api/state').json()
        assert after['vehicles']==frozen['vehicles'] and after['signals']==frozen['signals']
        result['pause_freezes_traffic_and_signals']=True
        page.locator('#resume').click();expect(page.locator('#mode')).to_have_text('running')
        page.wait_for_timeout(350)
        assert page.request.get(args.url+'/api/state').json()['timestamp']>frozen['timestamp']
        result['resume']=True
        page.locator('#stop').click();expect(page.locator('#mode')).to_have_text('stopped')
        page.locator('#reset').click();expect(page.locator('#clock')).to_contain_text('0.0')
        expect(page.locator('#phase')).to_have_text('N GREEN')
        result['stop_and_reset']=True
        context.set_offline(True)
        # Chromium's offline emulation doesn't reliably terminate an already-open WS.
        page.evaluate("socket.close(1000,'network loss test')")
        expect(page.locator('#connection')).to_contain_text('Offline')
        expect(page.locator('#apply')).to_be_disabled()
        context.set_offline(False);expect(page.locator('#connection')).to_contain_text('online',timeout=8000)
        expect(page.locator('#apply')).to_be_enabled();result['websocket_network_recovery']=True
        # Restore a useful running scene, with shorter phases for observation.
        for name,value in {'green_ns':'12','green_ew':'12','desired_speed':'50',
                           'simulation_speed':'2','demand_north':'300','demand_east':'300'}.items():
            page.locator(f'[name="{name}"]').fill(value)
        page.locator('#apply').click();expect(page.locator('#applied')).to_contain_text('Applied')
        page.locator('#start').click();expect(page.locator('#mode')).to_have_text('running')
        page.wait_for_timeout(1500)
        health=page.request.get(args.url+'/api/health').json()
        assert health['blender_connected'],'Blender did not acknowledge applied traffic state'
        result['blender_connected_during_dashboard_controls']=True
        result['javascript_errors']=errors;assert not errors
        page.screenshot(path=str(ROOT/'artifacts/dashboard.png'),full_page=True)
        (ROOT/'artifacts/browser_smoke.json').write_text(json.dumps(result,indent=2))
        browser.close()
    print('TRAFFIC_BROWSER_SMOKE_PASS '+json.dumps(result))


if __name__=='__main__':main()
