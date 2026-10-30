// paperassist_golden_angle_hsl_v1, shared with the fixed Python renderer.
// Numeric cluster identities are bounded and canonical; missing IDs never shift colors.
export const UNKNOWN_CLUSTER_COLOR='#777777'
export const EXCLUDED_SPOT_COLOR='#9ca3af'
export function clusterIndex(value:string|null):number|null{return value!==null&&/^(0|[1-9][0-9]?)$/.test(value)&&Number(value)<50?Number(value):null}
export function clusterColor(value:string|null):string{
 const index=clusterIndex(value)
 if(index===null)return UNKNOWN_CLUSTER_COLOR
 const hue=(index*137.50776405003785)%360,saturation=.65,lightness=.52
 const chroma=(1-Math.abs(2*lightness-1))*saturation,secondary=chroma*(1-Math.abs((hue/60)%2-1)),offset=lightness-chroma/2
 const rgb=hue<60?[chroma,secondary,0]:hue<120?[secondary,chroma,0]:hue<180?[0,chroma,secondary]:hue<240?[0,secondary,chroma]:hue<300?[secondary,0,chroma]:[chroma,0,secondary]
 return '#'+rgb.map(channel=>Math.round((channel+offset)*255).toString(16).padStart(2,'0')).join('')
}
