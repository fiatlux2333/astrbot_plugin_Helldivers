<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', padding:'20px 64px', flexDirection:'column' }}>
  <Box style={{ height:96, flexDirection:'row', alignItems:'center' }}>
    <Box style={{ width:8, height:48, background:'#3D9BE9', borderRadius:4, marginRight:18 }} />
    <Text style={{ fontSize:36, fontWeight:'bold', color:'#EAF1FB' }}>模块架构一览</Text>
  </Box>
  <Box style={{ height:504, flexDirection:'column', justifyContent:'space-between' }}>
    {[
      { name:'数据层', c:'#3D9BE9', mods:['Community API', 'Steam News', 'Companion', 'Helldivers Wiki', '银河快报 B站'] },
      { name:'服务编排', c:'#3D9BE9', mods:['缓存', 'AI 翻译', '查询', '图片渲染 (services)'] },
      { name:'指令 / 推送', c:'#F5A623', mods:['AstrBot 指令', '主动消息 (main.py)'] },
      { name:'平台层', c:'#5BA85B', mods:['QQ', 'QQ 官方', 'Telegram', 'Discord'] },
    ].map((layer, i) => (
      <Box key={i}>
        <Box style={{ background:'#10213B', borderRadius:12, padding:'14px 22px', flexDirection:'row', alignItems:'center', gap:18, borderLeft:`4px solid ${layer.c}` }}>
          <Text style={{ fontSize:19, fontWeight:'bold', color:layer.c, width:120 }}>{layer.name}</Text>
          <Box style={{ flex:1, flexDirection:'row', flexWrap:'wrap', gap:10 }}>
            {layer.mods.map((m, j) => (
              <Box key={j} style={{ background:'rgba(255,255,255,0.05)', borderRadius:8, padding:'8px 16px' }}>
                <Text style={{ fontSize:16, color:'#EAF1FB' }}>{m}</Text>
              </Box>
            ))}
          </Box>
        </Box>
        {i < 3 && <Box style={{ alignItems:'center', padding:'4px 0' }}><FAIcon name='arrow-down' style={{ fill:'#8FA3BF', width:20, height:20 }} /></Box>}
      </Box>
    ))}
  </Box>
  <Box style={{ height:60, flexDirection:'row', justifyContent:'space-between', alignItems:'center' }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>HD2 · 绝地潜兵2数据查询助手</Text>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>10 / 12</Text>
  </Box>
</Slide>
