<Slide style={{ width:'1280px', height:'720px', background:'#0B1424', position:'relative', overflow:'hidden' }}>
  <svg width='1280' height='720' viewBox='0 0 1280 720' style={{ position:'absolute', top:0, left:0 }}>
    <defs>
      <radialGradient id='gal' cx='55%' cy='45%' r='60%'>
        <stop offset='0%' stopColor='#16335C' stopOpacity='0.9' />
        <stop offset='100%' stopColor='#0B1424' stopOpacity='0' />
      </radialGradient>
    </defs>
    <rect width='1280' height='720' fill='#0B1424' />
    <ellipse cx='700' cy='360' rx='820' ry='460' fill='url(#gal)' />
    <circle cx='420' cy='400' r='170' fill='#5BA85B' opacity='0.10' />
    <circle cx='860' cy='280' r='150' fill='#D64545' opacity='0.10' />
    <circle cx='640' cy='540' r='130' fill='#9B6BD6' opacity='0.10' />
    <line x1='420' y1='400' x2='860' y2='280' stroke='#5BA85B' strokeOpacity='0.3' strokeWidth='1.5' />
    <line x1='860' y1='280' x2='640' y2='540' stroke='#D64545' strokeOpacity='0.3' strokeWidth='1.5' />
    <line x1='640' y1='540' x2='420' y2='400' stroke='#9B6BD6' strokeOpacity='0.3' strokeWidth='1.5' />
    <circle cx='420' cy='400' r='10' fill='#5BA85B' />
    <circle cx='360' cy='320' r='6' fill='#5BA85B' />
    <circle cx='480' cy='470' r='6' fill='#5BA85B' />
    <circle cx='860' cy='280' r='10' fill='#D64545' />
    <circle cx='930' cy='220' r='6' fill='#D64545' />
    <circle cx='800' cy='360' r='6' fill='#D64545' />
    <circle cx='640' cy='540' r='10' fill='#9B6BD6' />
    <circle cx='700' cy='600' r='6' fill='#9B6BD6' />
    <circle cx='560' cy='500' r='5' fill='#EAF1FB' />
    <circle cx='1000' cy='430' r='5' fill='#EAF1FB' />
    <circle cx='300' cy='220' r='4' fill='#EAF1FB' />
    <circle cx='1080' cy='320' r='4' fill='#EAF1FB' />
    <circle cx='520' cy='180' r='4' fill='#EAF1FB' />
    <circle cx='760' cy='160' r='3' fill='#EAF1FB' />
  </svg>
  <Box style={{ position:'absolute', top:0, left:0, width:'100%', height:'100%', background:'rgba(11,20,36,0.5)' }} />
  <Box style={{ position:'relative', zIndex:2, height:140, padding:'44px 64px 0' }}>
    <Text style={{ fontSize:17, letterSpacing:4, color:'#F5A623', fontWeight:'bold', marginBottom:10 }}>THE GALACTIC WAR MAP</Text>
    <Text style={{ fontSize:40, fontWeight:'bold', color:'#EAF1FB' }}>银河战争地图与民主空间站</Text>
  </Box>
  <Box style={{ position:'absolute', right:64, top:300, width:470, zIndex:2, background:'rgba(16,33,59,0.88)', border:'1px solid #16335C', borderRadius:16, padding:'26px 28px' }}>
    <Box style={{ flexDirection:'row', alignItems:'center', gap:14, marginBottom:16 }}>
      <FAIcon name='map' style={{ fill:'#3D9BE9', width:30, height:30 }} />
      <Text style={{ fontSize:21, fontWeight:'bold', color:'#EAF1FB' }}>/map 银河战争地图</Text>
    </Box>
    <Text style={{ fontSize:18, color:'#9FB3CC', lineHeight:1.6, marginBottom:18 }}>阵营控制区、战役与活跃星球，全部标注在图上。</Text>
    <Box style={{ flexDirection:'row', alignItems:'center', gap:14, marginBottom:16 }}>
      <FAIcon name='satellite-dish' style={{ fill:'#F5A623', width:30, height:30 }} />
      <Text style={{ fontSize:21, fontWeight:'bold', color:'#EAF1FB' }}>/dss 民主空间站</Text>
    </Box>
    <Text style={{ fontSize:18, color:'#9FB3CC', lineHeight:1.6, marginBottom:18 }}>完整主面板中文情报，战术行动一目了然。</Text>
    <Box style={{ flexDirection:'row', alignItems:'center', gap:14 }}>
      <FAIcon name='globe' style={{ fill:'#5BA85B', width:30, height:30 }} />
      <Text style={{ fontSize:21, fontWeight:'bold', color:'#EAF1FB' }}>/planet 星球详情</Text>
    </Box>
    <Text style={{ fontSize:18, color:'#9FB3CC', lineHeight:1.6, marginTop:8 }}>支持中文名 / 英文名 / 编号 / 链接任意解析。</Text>
  </Box>
  <Box style={{ position:'absolute', bottom:18, right:64, zIndex:2 }}>
    <Text style={{ fontSize:14, color:'#8FA3BF' }}>07 / 12</Text>
  </Box>
</Slide>
