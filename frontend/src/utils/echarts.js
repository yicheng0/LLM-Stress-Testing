let echartsPromise

export async function loadEcharts() {
  if (!echartsPromise) {
    echartsPromise = Promise.all([
      import('echarts/core'),
      import('echarts/charts'),
      import('echarts/components'),
      import('echarts/renderers')
    ]).then(([core, charts, components, renderers]) => {
      const { BarChart, HeatmapChart, LineChart, PieChart, ScatterChart } = charts
      const {
        DataZoomComponent,
        GridComponent,
        LegendComponent,
        MarkLineComponent,
        TitleComponent,
        TooltipComponent,
        VisualMapComponent
      } = components
      const { CanvasRenderer } = renderers

      core.use([
        BarChart,
        HeatmapChart,
        LineChart,
        PieChart,
        ScatterChart,
        DataZoomComponent,
        GridComponent,
        LegendComponent,
        MarkLineComponent,
        TitleComponent,
        TooltipComponent,
        VisualMapComponent,
        CanvasRenderer
      ])

      return core
    })
  }
  return echartsPromise
}
