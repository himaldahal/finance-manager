    #   var ctx = document.getElementById('bymonthgraph').getContext('2d');
    #     var myChart = new Chart(ctx, {
    #       type: 'bar',
    #       data: chartData,
    #       options: {
    #         scales: {
    #           y: {
    #             beginAtZero: true
    #           }
    #         },
    #         plugins: {
    #           legend: {
    #             display: false
    #           }
    #         },
    #         layout: {
    #           padding: {
    #             left: 20,
    #             right: 20,
    #             top: 0,
    #             bottom: 20,
    #           }
    #         },
    #         cornerRadius: 10,
    #         borderWidth: 0,
    #         barPercentage: 0.8,
    #         categoryPercentage: 1.0,
    #         responsive: true,
    #         maintainAspectRatio: false,
    #         barThickness: 30, 
    #         maxBarThickness: 30,
    #         cornerRadius: 10,
    #         animation: {
    #           duration: 1500
    #         }
    #       },

    #       plugins: [{
    #         beforeInit: function(chart) {
    #           chart.data.datasets.forEach(function(dataset) {
    #             dataset.backgroundColor = '#3457D5';
    #           });
    #         }
    #       }]
    #     });